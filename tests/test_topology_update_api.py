"""Online topology API boundaries and session lifecycle; FakeHost only."""
import copy
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_lab import FakeHost, example
from lab_core import LabError, LabManager
from lab_capture import CaptureService
from lab_terminal import TerminalService
from lab_server import create_app, join_jobs


class DummyTerminal:
    def __init__(self, lab):
        self.target = {"lab": lab}
        self.closed = False

    async def close(self):
        self.closed = True


class TopologyUpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.record = self.manager.save(example())
        self.manager.deploy(self.record)
        self.base = copy.deepcopy(self.manager.read("first-lab")["topology"])
        self.terminals = TerminalService(self.manager)
        self.captures = CaptureService(self.manager, spawn=lambda session: None)
        self.client = TestClient(create_app(self.manager, "update-test", terminals=self.terminals, captures=self.captures))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"Authorization": "Bearer update-test"}

    def payload(self):
        topology = copy.deepcopy(self.base)
        topology["nodes"][-1]["ports"][0]["address"] = "10.10.2.20/24"
        return {"topology": topology, "base": copy.deepcopy(self.base)}

    def post(self, payload, **kwargs):
        return self.client.post("/api/labs/first-lab/update", json=payload, headers=self.headers, **kwargs)

    def wait_job(self):
        deadline = time.monotonic() + 5
        while self.manager.busy is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(self.manager.busy, "update job did not finish")
        return self.manager.read("first-lab")

    def test_auth_origin_and_invalid_payloads_do_not_start_jobs_or_close_sessions(self):
        session = DummyTerminal("first-lab")
        self.terminals.sessions.add(session)
        original = self.manager.path("first-lab").read_bytes()
        calls = len(self.host.calls)
        self.assertEqual(self.client.post("/api/labs/first-lab/update", json=self.payload()).status_code, 401)
        self.assertEqual(self.client.post("/api/labs/first-lab/update", json=self.payload(),
                         headers={**self.headers, "Origin": "https://untrusted.invalid"}).status_code, 403)
        invalid = [{}, {"topology": self.base}, {**self.payload(), "command": "unexpected"}]
        wrong_id = self.payload()
        wrong_id["topology"]["id"] = "other-lab"
        invalid.append(wrong_id)
        stale = self.payload()
        stale["base"]["name"] = "outdated name"
        invalid.append(stale)
        for payload in invalid:
            with self.subTest(payload_keys=list(payload)):
                self.assertEqual(self.post(payload).status_code, 400)
        self.assertIsNone(self.manager.busy)
        self.assertFalse(session.closed)
        self.assertEqual(self.manager.path("first-lab").read_bytes(), original)
        self.assertEqual(len(self.host.calls), calls)

    def test_update_synchronizes_runtime_and_closes_only_this_labs_sessions(self):
        other = example()
        other["id"] = "other-lab"
        self.manager.deploy(self.manager.save(other))
        first_ticket = self.terminals.issue("first-lab", "r1", "shell")["ticket"]
        other_ticket = self.terminals.issue("other-lab", "r1", "shell")["ticket"]
        self.captures.issue("first-lab", {"link": "l1"})
        self.captures.issue("other-lab", {"link": "l1"})
        first_session, other_session = DummyTerminal("first-lab"), DummyTerminal("other-lab")
        self.terminals.sessions.update([first_session, other_session])
        containers = copy.deepcopy(self.record["runtime"]["nodes"])
        payload = self.payload()
        response = self.post(payload)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["runtime"]["phase"], "updating")
        self.assertEqual(response.json()["topology"], self.base)
        record = self.wait_job()
        self.assertEqual(record["runtime"]["phase"], "running", record["runtime"].get("error"))
        self.assertEqual(record["topology"], payload["topology"])
        self.assertEqual(record["runtime"]["nodes"], containers)
        self.assertTrue(first_session.closed)
        self.assertFalse(other_session.closed)
        with self.assertRaises(LabError):
            self.terminals.consume(first_ticket)
        self.assertEqual(self.terminals.consume(other_ticket)["lab"], "other-lab")
        self.assertEqual(self.captures.list("first-lab")[0]["state"], "stopped")
        self.assertNotEqual(self.captures.list("other-lab")[0]["state"], "stopped")

    def test_display_only_save_does_not_interrupt_running_sessions(self):
        session = DummyTerminal("first-lab")
        self.terminals.sessions.add(session)
        topology = copy.deepcopy(self.base)
        topology["nodes"][0]["x"] += 40
        topology["annotations"] = [{"id": "subnet", "text": "10.10.1.0/24", "x": 20, "y": 60,
                                     "fontSize": 16, "color": "#123456", "background": "none"}]
        calls = len(self.host.calls)
        response = self.client.put("/api/labs/first-lab", json=topology, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["topology"], topology)
        self.assertFalse(session.closed)
        self.assertEqual(len(self.host.calls), calls)
        self.assertEqual(response.json()["runtime"], self.manager.read("first-lab")["runtime"])

    def test_update_request_limit_allows_two_snapshots_but_stays_bounded(self):
        # Payload parsing is checked before the manager; use a stub to avoid huge fixtures.
        with patch.object(self.manager, "start_update", return_value=copy.deepcopy(self.record)) as update:
            response = self.post({"base": "x" * 600000, "topology": "y" * 600000})
            self.assertEqual(response.status_code, 202)
            update.assert_called_once()
            update.reset_mock()
            response = self.post({"base": "x" * (2 * 1024 * 1024)})
            self.assertEqual(response.status_code, 400)
            self.assertIn("2 MiB", response.json()["error"])
            update.assert_not_called()
        response = self.client.put("/api/labs/first-lab", json={"padding": "x" * (1024 * 1024)}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("1 MiB", response.json()["error"])

    def test_shutdown_waits_for_an_in_progress_update(self):
        entered, release, joining, finished = (threading.Event() for _ in range(4))
        update = self.manager.update

        def paused(record, topology):
            entered.set()
            if not release.wait(5):
                raise LabError("test update was not released")
            update(record, topology)

        def shutdown():
            joining.set()
            join_jobs()
            finished.set()

        with patch.object(self.manager, "update", side_effect=paused):
            response = self.post(self.payload())
            self.assertEqual(response.status_code, 202)
            worker = threading.Thread(target=shutdown)
            try:
                self.assertTrue(entered.wait(2))
                worker.start()
                self.assertTrue(joining.wait(2))
                self.assertFalse(finished.wait(0.1), "shutdown must wait for lab-update threads")
            finally:
                release.set()
                if worker.ident is not None:
                    worker.join(5)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.wait_job()["runtime"]["phase"], "running")


if __name__ == "__main__":
    unittest.main()
