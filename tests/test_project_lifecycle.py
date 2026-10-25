"""Remote project lifecycle and partial running-config persistence."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from test_lab import FakeHost, LabError, LabManager, example
from lab_devices import adapter_for, template_for
from lab_server import create_app


class ProjectLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.app = create_app(self.manager, "secret")
        self.headers = {"Authorization": "Bearer secret", "Origin": "http://testserver"}

    def tearDown(self):
        self.temp.cleanup()

    def deploy(self, topology=None):
        record = self.manager.save(topology or example())
        self.manager.deploy(record)
        return self.manager.read(record["topology"]["id"])

    def test_create_is_persistent_unique_and_visible_to_another_browser(self):
        with TestClient(self.app) as client:
            first = client.post("/api/labs", headers=self.headers, json={"name": "  远程项目  "})
            second = client.post("/api/labs", headers=self.headers, json={"name": "远程项目"})
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(second.status_code, 201, second.text)
            one, two = first.json(), second.json()
            lab_id = one["topology"]["id"]
            self.assertNotEqual(lab_id, two["topology"]["id"])
            self.assertEqual(one["topology"]["name"], "远程项目")
            self.assertEqual(one["topology"]["nodes"], [])
            self.assertTrue(self.manager.path(lab_id).is_file())
        reopened_manager = LabManager(self.temp.name, preview=True)
        with TestClient(create_app(reopened_manager, "secret")) as other_browser:
            listing = other_browser.get("/api/labs", headers=self.headers).json()
            self.assertEqual({item["id"] for item in listing}, {lab_id, two["topology"]["id"]})
            opened = other_browser.post(f"/api/labs/{lab_id}/open", headers=self.headers, json={})
            self.assertEqual(opened.status_code, 200)
            self.assertEqual(opened.json()["topology"], one["topology"])

    def test_project_endpoints_enforce_auth_origin_and_payload(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.post("/api/labs", json={"name": "A"}).status_code, 401)
            foreign = {**self.headers, "Origin": "http://foreign.example"}
            self.assertEqual(client.post("/api/labs", headers=foreign, json={"name": "A"}).status_code, 403)
            for value in ({"name": " "}, {"name": "x" * 81}, {"name": "A", "id": "chosen"}):
                self.assertEqual(client.post("/api/labs", headers=self.headers, json=value).status_code, 400)
            record = self.manager.create_project("A")
            lab_id = record["topology"]["id"]
            for action in ("open", "close", "save"):
                response = client.post(f"/api/labs/{lab_id}/{action}", headers=foreign, json={})
                self.assertEqual(response.status_code, 403)
            for action in ("open", "close"):
                response = client.post(f"/api/labs/{lab_id}/{action}", headers=self.headers, json={"host": "elsewhere"})
                self.assertEqual(response.status_code, 400)
            for payload in ({}, {"topology": None}, {"topology": {**record["topology"], "id": "other"}}):
                self.assertEqual(client.post(f"/api/labs/{lab_id}/save", headers=self.headers, json=payload).status_code, 400)

    def test_close_releases_sessions_but_preserves_project_and_devices(self):
        record = self.deploy()
        lab_id = record["topology"]["id"]
        before = self.manager.path(lab_id).read_bytes()
        containers = copy.deepcopy(self.host.containers)
        with TestClient(self.app) as client:
            with patch.object(self.app.state.terminals, "close_lab", new_callable=AsyncMock) as terminals, \
                    patch.object(self.app.state.captures, "close_lab", new_callable=AsyncMock) as captures:
                closed = client.post(f"/api/labs/{lab_id}/close", headers=self.headers, json={})
                self.assertEqual(closed.status_code, 200, closed.text)
                self.assertEqual(closed.json(), {"ok": True, "id": lab_id})
                terminals.assert_awaited_once_with(lab_id)
                captures.assert_awaited_once_with(lab_id)
            self.assertEqual(self.manager.path(lab_id).read_bytes(), before)
            self.assertEqual(self.host.containers, containers)
            opened = client.post(f"/api/labs/{lab_id}/open", headers=self.headers, json={})
            self.assertEqual(opened.json()["runtime"]["deployment"], record["runtime"]["deployment"])

    def test_busy_close_does_not_close_sessions_and_missing_projects_fail(self):
        record = self.manager.create_project("Busy")
        lab_id = record["topology"]["id"]
        self.manager.busy = lab_id
        with TestClient(self.app) as client:
            with patch.object(self.app.state.terminals, "close_lab", new_callable=AsyncMock) as terminals, \
                    patch.object(self.app.state.captures, "close_lab", new_callable=AsyncMock) as captures:
                self.assertEqual(client.post(f"/api/labs/{lab_id}/close", headers=self.headers, json={}).status_code, 400)
                terminals.assert_not_awaited()
                captures.assert_not_awaited()
            for action in ("open", "close"):
                self.assertEqual(client.post(f"/api/labs/missing/{action}", headers=self.headers, json={}).status_code, 400)
        self.manager.busy = None

    def test_undeployed_save_persists_topology_without_requiring_docker(self):
        self.manager.preview = True
        self.manager.authorize = lambda: self.fail("Undeployed project save must not require Docker")
        topology = example()
        with TestClient(self.app) as client:
            response = client.post("/api/labs/first-lab/save", headers=self.headers, json={"topology": topology})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertTrue(result["topology_saved"])
            self.assertEqual(result["results"], [])
            self.assertEqual(self.manager.read("first-lab")["topology"], result["record"]["topology"])
            self.assertEqual(self.host.calls, [])

    def test_save_includes_running_frr_configs_and_reports_unsupported_devices(self):
        record = self.deploy()
        topology = record["topology"]
        topology["nodes"][0]["x"] += 15
        cid = record["runtime"]["nodes"]["r1"]["id"]
        self.host.running_configs[cid] = "hostname REMOTE-SAVED\n"
        with TestClient(self.app) as client:
            response = client.post("/api/labs/first-lab/save", headers=self.headers, json={"topology": topology})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
        outcomes = {item["node"]: item for item in result["results"]}
        for node in topology["nodes"]:
            item = outcomes[node["id"]]
            supported = template_for(node)["capabilities"]["save_config"]
            self.assertEqual(item["ok"], supported)
            if not supported:
                self.assertTrue(item["skipped"])
        saved = result["record"]["topology"]["nodes"][0]
        self.assertEqual(saved["x"], topology["nodes"][0]["x"])
        self.assertEqual(saved["config"], "hostname REMOTE-SAVED")
        directory = Path(outcomes["r1"]["status"]["path"])
        self.assertEqual((directory / "frr.conf").read_text(), "hostname REMOTE-SAVED\n")
        for filename in ("daemons", "vtysh.conf"):
            self.assertTrue((directory / filename).is_file())

    def test_partial_save_keeps_successful_config_and_topology(self):
        initial = example()
        initial["nodes"].append({**copy.deepcopy(initial["nodes"][0]), "id": "r2", "name": "R2"})
        record = self.deploy(initial)
        topology = record["topology"]
        topology["name"] = "部分保存"
        for node_id in ("r1", "r2"):
            cid = record["runtime"]["nodes"][node_id]["id"]
            self.host.running_configs[cid] = "hostname SAVED-" + node_id + "\n"
        adapter = adapter_for(topology["nodes"][0])
        save_config = adapter.save_config

        def partial(manager, current, node):
            if node["id"] == "r2":
                raise LabError("模拟单设备失败")
            return save_config(manager, current, node)

        with patch.object(adapter, "save_config", side_effect=partial):
            result = self.manager.save_project(topology)
        outcomes = {item["node"]: item for item in result["results"]}
        self.assertTrue(outcomes["r1"]["ok"])
        self.assertFalse(outcomes["r2"]["ok"])
        self.assertNotIn("skipped", outcomes["r2"])
        self.assertIn("模拟单设备失败", outcomes["r2"]["error"])
        self.assertEqual(result["record"]["topology"]["name"], "部分保存")
        self.assertEqual(result["record"]["topology"]["nodes"][0]["config"], "hostname SAVED-r1")

    def test_busy_or_unapplied_network_changes_cannot_overwrite_saved_project(self):
        record = self.deploy()
        before = self.manager.path("first-lab").read_bytes()
        changed = copy.deepcopy(record["topology"])
        changed["nodes"][0]["ports"][0]["address"] = "198.51.100.1/24"
        with self.assertRaisesRegex(LabError, "应用拓扑"):
            self.manager.save_project(changed)
        self.assertEqual(self.manager.path("first-lab").read_bytes(), before)
        self.manager.busy = "other-project"
        with self.assertRaisesRegex(LabError, "进行中"):
            self.manager.save_project(record["topology"])
        self.assertEqual(self.manager.path("first-lab").read_bytes(), before)
        self.manager.busy = None


if __name__ == "__main__":
    unittest.main()
