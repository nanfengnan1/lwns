"""Capture ownership, tickets, streaming lifecycle and local launcher boundary."""
import asyncio
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from test_lab import FakeHost, example

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script" / "python"))
sys.path.insert(0, str(ROOT / "clients" / "capture"))
from lab_capture import CaptureService, PCAP_MAGIC
from lab_core import LabError, LabManager
from lab_server import create_app
import launcher

HEADER = struct.pack("<IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)


def fake_capture(session):
    if session.filter == "invalid BPF":
        script = "import sys;print('invalid capture filter',file=sys.stderr);sys.exit(1)"
    else:
        script = f"import sys,time;sys.stdout.buffer.write({HEADER!r});sys.stdout.buffer.flush();time.sleep(0.1 if {session.filter!r}=='finite' else 60)"
    return subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        topology = example()
        self.lab_id, self.link = topology["id"], topology["links"][0]
        self.manager.save(topology)
        self.manager.deploy(self.manager.read(self.lab_id))
        self.service = CaptureService(self.manager, port=18106, spawn=fake_capture)

    async def asyncTearDown(self):
        await self.service.close_lab()

    def issue(self, **extra):
        return self.service.issue(self.lab_id, {"link": self.link["id"], **extra})

    async def test_client_report_is_separate_one_use_and_cannot_fake_running(self):
        claim = self.service.claim(self.issue()["ticket"])
        payload = {"status": "launched", "output_file": "C:/captures/session/capture.pcapng", "manual_auth": True}
        with self.assertRaises(LabError):
            self.service.client_report({**payload, "ticket": claim["stream_ticket"]})
        with self.assertRaises(LabError):
            self.service.client_report({**payload, "ticket": claim["client_ticket"], "output_file": "bad\npath"})
        state = self.service.client_report({**payload, "ticket": claim["client_ticket"]})
        self.assertEqual(state["state"], "ready")
        self.assertTrue(state["client"]["manual_auth"])
        self.assertEqual(state["client"]["output_file"], payload["output_file"])
        with self.assertRaises(LabError):
            self.service.client_report({**payload, "ticket": claim["client_ticket"]})
        session = await self.service.open(claim["stream_ticket"])
        self.assertEqual(session.state, "running")

    async def test_launcher_failure_ends_pending_connection_and_invalidates_stream(self):
        claim = self.service.claim(self.issue()["ticket"])
        self.service.client_report({"ticket": claim["client_ticket"], "status": "error", "error": "Wireshark exited"})
        state = self.service.list(self.lab_id)[0]
        self.assertEqual(state["state"], "error")
        self.assertEqual(state["error"], "Wireshark exited")
        with self.assertRaises(LabError):
            await self.service.open(claim["stream_ticket"])

    async def test_ticket_types_one_use_expiry_and_stop_pending(self):
        issued = self.issue()
        with self.assertRaises(LabError):
            self.service.consume(issued["ticket"], "stream")
        claim = self.service.claim(issued["ticket"])
        self.assertEqual(claim["port"], 18106)
        with self.assertRaises(LabError):
            self.service.claim(issued["ticket"])
        await self.service.close_lab(self.lab_id, claim["session"]["id"])
        with self.assertRaises(LabError):
            await self.service.open(claim["stream_ticket"])
        issued = self.issue()
        self.service.sessions[issued["session"]["id"]].deadline = time.monotonic() - 1
        with self.assertRaises(LabError):
            self.service.claim(issued["ticket"])
        self.assertEqual(self.service.list(self.lab_id)[0]["state"], "expired")

    async def test_stream_header_and_stop_reap_process(self):
        claim = self.service.claim(self.issue()["ticket"])
        session = await self.service.open(claim["stream_ticket"])
        self.assertEqual(session.state, "running")
        stream = session.stream()
        self.assertEqual(await anext(stream), HEADER)
        await self.service.close_lab(self.lab_id, session.id)
        await stream.aclose()
        self.assertIsNotNone(session.process.poll())
        self.assertEqual(session.state, "stopped")
        self.assertEqual(session.bytes, 24)
        self.assertIsNone(session.error or None)

    async def test_stream_disconnect_reaps_process(self):
        session = await self.service.open(self.service.claim(self.issue()["ticket"])["stream_ticket"])
        stream = session.stream()
        await anext(stream)
        await stream.aclose()
        self.assertTrue(session.closed)
        self.assertIsNotNone(session.process.poll())

    async def test_invalid_filter_is_an_error_without_pcap(self):
        claim = self.service.claim(self.issue(filter="invalid BPF")["ticket"])
        with self.assertRaisesRegex(LabError, "invalid capture filter"):
            await self.service.open(claim["stream_ticket"])
        state = self.service.list(self.lab_id)[0]
        self.assertEqual(state["state"], "error")
        self.assertEqual(state["bytes"], 0)

    async def test_current_container_and_both_interface_peers_are_checked(self):
        original = self.manager.capture_target(self.lab_id, self.link["id"], "a")
        interface = self.host.interfaces[original["container"]][original["port"]]
        alias = interface["ifalias"]
        interface["ifalias"] = "foreign"
        with self.assertRaisesRegex(LabError, "归属"):
            self.issue()
        interface["ifalias"] = alias
        interface["link_index"] += 100
        with self.assertRaisesRegex(LabError, "对端"):
            self.issue()
        interface["link_index"] -= 100
        issued = self.issue()
        self.host.containers[original["container"]]["State"]["Pid"] += 100
        with self.assertRaisesRegex(LabError, "重启"):
            self.service.claim(issued["ticket"])
        self.assertEqual(self.service.list(self.lab_id)[0]["state"], "error")

    async def test_input_limits_deployment_busy_and_session_cap(self):
        for extra in ({"side": "x"}, {"filter": "icmp\n"}, {"filter": "x" * 1025}, {"snaplen": True}, {"snaplen": 63}, {"snaplen": 262145}):
            with self.assertRaises(LabError): self.issue(**extra)
        self.manager.busy = self.lab_id
        with self.assertRaises(LabError): self.issue()
        self.manager.busy = None
        for _ in range(8): self.issue()
        with self.assertRaisesRegex(LabError, "上限"): self.issue()

    async def test_target_change_before_stream_start_refuses_capture(self):
        claim = self.service.claim(self.issue()["ticket"])
        original = self.manager.capture_target(self.lab_id, self.link["id"], "a")
        self.host.interfaces[original["container"]][original["port"]]["ifindex"] += 10
        with self.assertRaises(LabError):
            await self.service.open(claim["stream_ticket"])
        self.assertEqual(self.service.list(self.lab_id)[0]["state"], "error")

    async def test_http_auth_download_claim_and_loopback_stream(self):
        headers = {"Authorization": "Bearer capture-test"}
        app = create_app(self.manager, "capture-test", captures=self.service)
        with TestClient(app, client=("127.0.0.1", 4000)) as client:
            path = f"/api/labs/{self.lab_id}/captures"
            self.assertEqual(client.post(path, json={"link": self.link["id"]}).status_code, 401)
            self.assertEqual(client.post(path, json={}, headers={**headers, "Origin": "https://foreign.test"}).status_code, 403)
            package = client.get("/api/capture/client", headers=headers)
            self.assertEqual(package.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
                self.assertIn("launcher.py", archive.namelist())
                self.assertIn("install.ps1", archive.namelist())
            issued = client.post(path, json={"link": self.link["id"], "filter": "finite"}, headers=headers).json()
            self.assertEqual(client.post("/api/capture/claim", json={"ticket": issued["ticket"]}, headers={"Origin": "https://foreign.test"}).status_code, 400)
            claim = client.post("/api/capture/claim", json={"ticket": issued["ticket"]})
            self.assertEqual(claim.status_code, 200, claim.text)
            ticket = claim.json()["stream_ticket"]
            report = {"ticket": claim.json()["client_ticket"], "status": "launched", "output_file": "C:/capture.pcapng", "manual_auth": True}
            self.assertEqual(client.post("/api/capture/client-report", json=report, headers={"Origin": "https://foreign.test"}).status_code, 400)
            self.assertEqual(client.post("/api/capture/client-report", json=report).status_code, 200)
            self.assertEqual(client.post("/api/capture/client-report", json=report).status_code, 400)
            response = client.post("/api/capture/stream", json={"ticket": ticket})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, HEADER)
            self.assertEqual(client.post("/api/capture/stream", json={"ticket": ticket}).status_code, 400)
            self.assertEqual(client.get(path, headers=headers).json()[0]["state"], "stopped")
        with TestClient(app, client=("192.0.2.20", 4000)) as client:
            self.assertEqual(client.post("/api/capture/stream", json={"ticket": "x" * 43}).status_code, 403)


class LauncherTests(unittest.TestCase):
    def test_configure_uri_has_no_ticket_or_arbitrary_command(self):
        self.assertEqual(launcher.parse_uri("route-ovs://configure?server=http%3A%2F%2Fhost%3A8090"), ("http://host:8090", None))
        with self.assertRaises(ValueError):
            launcher.parse_uri("route-ovs://configure?server=http://host&command=calc")

    def test_capture_path_is_unique_local_and_used_with_live_display(self):
        with tempfile.TemporaryDirectory() as temp:
            connection = {"capture_dir": temp, "wireshark": "wireshark", "profile": "", "host": "host", "port": 22, "username": "user", "sshkey": "", "autostart": False}
            descriptor = {"port": 8090, "stream_ticket": "T" * 43, "session": {"label": "../../R1 / eth0"}}
            first, second = [launcher.capture_file(connection, descriptor) for _ in range(2)]
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent.parent, Path(temp))
            self.assertEqual(first.name, "capture.pcapng")
            args = launcher.command(connection, "sshdump", "sshdump", descriptor, first)
            self.assertEqual(args[args.index("-w") + 1], str(first))
            self.assertIn("-S", args)
            self.assertIn("capture.pcap_ng:TRUE", args)
            self.assertNotIn("-F", args)  # Wireshark 4.2 GUI does not support -F.
            self.assertNotIn("-k", args)
            connection["autostart"] = True
            self.assertIn("-k", launcher.command(connection, "sshdump", "sshdump", descriptor, first))

    def test_tshark_is_not_accepted_as_the_graphical_application(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tshark"; path.touch()
            with self.assertRaisesRegex(ValueError, "图形程序"):
                launcher.validate_connection({"wireshark": str(path), "host": "host", "port": 22, "username": "user"})

    def test_launch_detects_early_exit_and_redacts_ticket_in_diagnostics(self):
        process = subprocess.Popen([sys.executable, "-c", "import sys;sys.stderr.write('bad argument ' + 'T' * 43);sys.exit(2)"], stderr=subprocess.PIPE)
        with patch.object(launcher.subprocess, "Popen", return_value=process), patch.object(launcher, "command", return_value=[]), patch.object(launcher, "activate_window", return_value=False), patch.object(launcher, "diagnostic") as diagnostic:
            with self.assertRaisesRegex(ValueError, "Wireshark 提前退出"):
                launcher.launch({}, "sshdump", "sshdump", {"stream_ticket": "T" * 43}, Path("capture.pcapng"))
            self.assertNotIn("T" * 43, diagnostic.call_args.args[0])
            self.assertIn("bad argument", diagnostic.call_args.args[0])

    def test_windowless_launcher_help_does_not_require_console_streams(self):
        with patch.object(sys, "argv", ["launcher", "--help"]), patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
            try:
                with self.assertRaises(SystemExit) as result:
                    launcher.main()
                self.assertEqual(result.exception.code, 0)
            finally:
                if sys.stdout: sys.stdout.close()
                if sys.stderr: sys.stderr.close()

    def test_uri_rejects_unknown_commands_credentials_and_repeated_arguments(self):
        token = "A" * 43
        server, ticket = launcher.parse_uri("route-ovs://capture?server=http%3A%2F%2Fexample.test%3A8090&ticket=" + token)
        self.assertEqual((server, ticket), ("http://example.test:8090", token))
        for uri in ("route-ovs://exec?server=http://x&ticket=" + token, "route-ovs://capture?server=http://x&ticket=x", "route-ovs://capture?server=http://x&ticket=" + token + "&command=cmd", "route-ovs://capture?server=http://x&server=http://y&ticket=" + token, "route-ovs://capture?server=http://user:pass@x&ticket=" + token):
            with self.assertRaises(ValueError): launcher.parse_uri(uri)

    def test_connection_settings_never_store_password_and_command_uses_detected_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / ("wireshark.exe" if os.name == "nt" else "wireshark")
            executable.touch()
            config = launcher.validate_connection({"wireshark": str(executable), "host": "10.8.126.103", "port": 22, "username": "alexan", "profile": "SSH-host", "sshkey": "", "autostart": True, "password": "do-not-save"})
            self.assertNotIn("password", config)
            args = launcher.command(config, "sshdump.exe", "sshdump_exe", {"port": 8090, "stream_ticket": "B" * 43})
            self.assertIn("SSH-host", args)
            self.assertIn("extcap.sshdump_exe.remotecapturecommandselect:other", args)
            self.assertIn("extcap.sshdump_exe.remotepriv:none", args)
            self.assertEqual(args[-3:], ["-i", "sshdump.exe", "-k"])
            self.assertNotIn("do-not-save", " ".join(args))
            path = Path(temp) / "client.json"
            launcher.save_config(path, {"version": 1, "connections": {"http://host:8090": config}})
            self.assertNotIn("password", path.read_text())
            config["autostart"] = False
            self.assertNotIn("-k", launcher.command(config, "sshdump", "sshdump", {"port": 8090, "stream_ticket": "B" * 43}))


if __name__ == "__main__":
    unittest.main()
