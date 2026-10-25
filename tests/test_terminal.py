"""Terminal auth tests; opt-in Docker integration: LWNS_DOCKER_TESTS=1.

Integration creates only uniquely named, labelled network=none test containers.
It uses Docker group access without exercising root-only veth deployment.
"""
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
import httpx
import uvicorn
from fastapi.testclient import TestClient
from websockets.asyncio.client import connect
from lab_core import LABEL, FRR_START, LabError, LabManager
from lab_server import create_app
from lab_terminal import TerminalService
from test_lab import FakeHost, example


class TerminalAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.record = self.manager.save(example())
        self.manager.deploy(self.record)
        self.terminals = TerminalService(self.manager)

    def tearDown(self):
        self.temp.cleanup()

    def test_ticket_single_use_expiry_and_mode(self):
        ticket = self.terminals.issue("first-lab", "r1", "default")["ticket"]
        self.assertEqual(self.terminals.consume(ticket)["program"], "vtysh")
        with self.assertRaises(LabError): self.terminals.consume(ticket)
        ticket = self.terminals.issue("first-lab", "r1", "shell")["ticket"]
        with patch("lab_terminal.time.monotonic", return_value=time.monotonic() + 31):
            with self.assertRaises(LabError): self.terminals.consume(ticket)
        with self.assertRaises(LabError): self.terminals.issue("first-lab", "r1", "bash;id")

    def test_target_rechecks_ownership_restart_and_redeployment(self):
        target = self.manager.terminal_target("first-lab", "r1")
        item = self.host.containers[target["container"]]
        item["State"]["Pid"] += 1
        with self.assertRaises(LabError): self.manager.terminal_target("first-lab", "r1", expected=target)
        item["State"]["Pid"] -= 1
        item["Config"]["Labels"][LABEL + ".deployment"] = "foreign"
        with self.assertRaises(LabError): self.manager.terminal_target("first-lab", "r1")
        item["Config"]["Labels"][LABEL + ".deployment"] = target["deployment"]
        self.manager.destroy(self.record)
        self.manager.deploy(self.record)
        with self.assertRaisesRegex(LabError, "变化"):
            self.manager.terminal_target("first-lab", "r1", expected=target)

    def test_http_auth_ws_origin_invalid_ticket_and_preview(self):
        with TestClient(create_app(self.manager, "secret", terminals=self.terminals)) as client:
            self.assertEqual(client.post("/api/labs/first-lab/terminals", json={"node": "r1"}).status_code, 401)
            for headers in ({}, {"origin": "http://foreign.invalid"}):
                from starlette.websockets import WebSocketDisconnect
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect("/api/terminal", headers=headers): pass
            with client.websocket_connect("/api/terminal", headers={"origin": "http://testserver"}) as ws:
                ws.send_json({"type": "connect", "ticket": "bad"})
                self.assertEqual(ws.receive_json()["type"], "error")
        preview = LabManager(self.temp.name, preview=True)
        with self.assertRaisesRegex(LabError, "设计模式"):
            TerminalService(preview).issue("first-lab", "r1", "default")


class DockerFixture:
    """Disposable fixtures shared by real WS and browser checks."""
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lwns-terminal-test-")
        self.manager = LabManager(self.temp.name)
        self.lab_id = "term-test-" + uuid.uuid4().hex[:12]
        self.created = []
        topology = {"version": 1, "id": self.lab_id, "name": "Web 终端验证", "links": [], "nodes": []}
        for node, kind, image, x in (("r1", "router", "alpine/frr:latest", 280),
                                    ("pc1", "host", "alpine/vpcs:latest", 520)):
            topology["nodes"].append({"id": node, "name": node.upper(), "kind": kind, "image": image,
                                      "x": x, "y": 220, "ports": [{"name": "eth0", "address": ""}],
                                      "gateway": "", "command": [], "config": ""})
        self.record = self.manager.save(topology)
        self.record["runtime"].update(deployment=uuid.uuid4().hex, phase="running")

    def start(self):
        for node in self.record["topology"]["nodes"]:
            self.manager.dock("image", "inspect", node["image"])
            args = ["create", "--name", self.lab_id + "-" + node["id"], "--hostname", node["name"],
                    "--network", "none", "--label", LABEL + "=" + self.lab_id,
                    "--label", LABEL + ".deployment=" + self.record["runtime"]["deployment"],
                    "--label", LABEL + ".node=" + node["id"], "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW"]
            command = ["sleep", "infinity"]
            if node["kind"] == "router":
                args += ["--cap-add", "SYS_ADMIN"]
                command = ["sh", "-c", FRR_START]
            cid = self.manager.dock(*(args + [node["image"]] + command))
            self.created.append(cid)
            self.manager.dock("start", cid)
            item = self.manager.inspect(cid)
            self.record["runtime"]["nodes"][node["id"]] = {"id": cid, "name": item["Name"], "pid": item["State"]["Pid"]}
        self.manager.write(self.record)
        # Only this test instance bypasses root/veth readiness. Production does not.
        self.manager.authorize = lambda: None
        self.manager.environment = lambda: {"ready": True, "preview": False, "errors": [], "images": []}
        for _ in range(30):
            try:
                self.manager.dock("exec", self.record["runtime"]["nodes"]["r1"]["id"], "vtysh", "-c", "show version")
                break
            except LabError:
                time.sleep(0.2)
        return self

    def close(self):
        for cid in self.created:
            try:
                item = self.manager.inspect(cid)
                self.manager.owned(self.record, item)
                self.manager.dock("rm", "-f", "-v", cid)
            except LabError as exc:
                print("Test fixture cleanup:", exc, file=sys.stderr)
        self.temp.cleanup()


@unittest.skipUnless(os.environ.get("LWNS_DOCKER_TESTS") == "1", "opt-in real Docker test")
class DockerTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = DockerFixture()
        self.addAsyncCleanup(self.cleanup)
        await asyncio.to_thread(self.fixture.start)
        self.manager = self.fixture.manager
        self.terminals = TerminalService(self.manager)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.base = "http://127.0.0.1:" + str(self.port)
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.manager, "test", terminals=self.terminals),
                                                   log_level="error", ws="websockets-sansio", lifespan="on"))
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.sock]))
        for _ in range(100):
            if self.server.started: break
            await asyncio.sleep(.02)
        self.client = httpx.AsyncClient(base_url=self.base, headers={"Authorization": "Bearer test"})

    async def cleanup(self):
        if hasattr(self, "terminals"): await self.terminals.close_lab()
        if hasattr(self, "client"): await self.client.aclose()
        if hasattr(self, "server"):
            self.server.should_exit = True
            await asyncio.wait_for(self.server_task, 10)
        await asyncio.to_thread(self.fixture.close)

    async def open_terminal(self, node="pc1", mode="default"):
        response = await self.client.post("/api/labs/" + self.fixture.lab_id + "/terminals", json={"node": node, "mode": mode})
        self.assertEqual(response.status_code, 201, response.text)
        ws = await connect("ws://127.0.0.1:" + str(self.port) + "/api/terminal", origin=self.base)
        await ws.send(json.dumps({"type": "connect", "ticket": response.json()["ticket"], "cols": 100, "rows": 24}))
        message = json.loads(await asyncio.wait_for(ws.recv(), 5))
        self.assertEqual(message["type"], "ready", message)
        return ws

    async def until(self, ws, expected):
        text = ""
        async with asyncio.timeout(8) if hasattr(asyncio, "timeout") else AsyncTimeout(8):
            while expected not in text:
                message = await ws.recv()
                if isinstance(message, bytes):
                    text += message.decode("utf-8", errors="replace")
                    await ws.send('{"type":"ack"}')
                else:
                    value = json.loads(message)
                    self.assertNotEqual(value["type"], "error", value)
                    if value["type"] == "exit": self.fail("Unexpected exit: " + text)
        return text

    async def input(self, ws, data):
        await ws.send(json.dumps({"type": "input", "data": data}))

    async def test_real_shell_resize_ctrl_c_frr_and_cleanup(self):
        shell = await self.open_terminal()
        await self.until(shell, "#")
        await self.input(shell, "cd /tmp\r")
        await self.until(shell, "#")
        await self.input(shell, "printf 'DIR=%s\\n' \"$PWD\"\r")
        await self.until(shell, "DIR=/tmp")
        await self.input(shell, "seq 1 5000\r")
        await self.until(shell, "5000\r\n")
        await shell.send('{"type":"resize","cols":111,"rows":31}')
        await asyncio.sleep(.2)
        await self.input(shell, "stty size\r")
        await self.until(shell, "31 111")
        await self.input(shell, "ping 127.0.0.1\r")
        await self.until(shell, "bytes from")
        await self.input(shell, "\u0003")
        await self.until(shell, "#")
        # A second interactive program works while the first connection remains open.
        router = await self.open_terminal("r1")
        await self.until(router, "R1#")
        await self.input(router, "configure terminal\r")
        await self.until(router, "R1(config)#")
        await self.input(router, "router ospf\r")
        await self.until(router, "R1(config-router)#")
        await self.input(router, "end\rshow ip route\r")
        await self.until(router, "R1#")
        self.assertEqual((await self.client.get("/api/labs")).status_code, 200)
        await router.close()
        # Close while a long-running child is active: neither shell nor ping may leak.
        await self.input(shell, "ping 127.0.0.1\r")
        await self.until(shell, "bytes from")
        session = next(s for s in self.terminals.sessions if s.target["node"] == "pc1")
        marker, cid = session.marker, session.target["container"]
        await shell.close()
        for _ in range(100):
            if not self.terminals.sessions: break
            await asyncio.sleep(.05)
        self.assertFalse(self.terminals.sessions)
        processes = await asyncio.to_thread(self.manager.dock, "exec", cid, "ps", "-eo", "args")
        self.assertNotIn("ping 127.0.0.1", processes)
        self.assertNotIn("sh -i", processes)
        self.assertTrue(self.manager.inspect(cid)["State"]["Running"])
        # Malformed frames close the session and do not leave a process behind.
        ws = await self.open_terminal()
        await self.until(ws, "#")
        await ws.send('{"type":"resize","cols":-1,"rows":24}')
        self.assertEqual(json.loads(await ws.recv())["type"], "error")
        await ws.close()
        # Clearing a lab with an active terminal closes it without blocking the job.
        ws = await self.open_terminal("r1")
        await self.until(ws, "R1#")
        response = await self.client.post("/api/labs/" + self.fixture.lab_id + "/destroy", json={})
        self.assertEqual(response.status_code, 202, response.text)
        await asyncio.wait_for(ws.wait_closed(), 8)
        for _ in range(100):
            if self.manager.busy is None and not self.terminals.sessions: break
            await asyncio.sleep(.05)
        self.assertFalse(self.terminals.sessions)
        self.assertEqual(self.manager.read(self.fixture.lab_id)["runtime"]["phase"], "idle")
        self.fixture.created.clear()  # The normal deployment cleanup removed them.


class AsyncTimeout:
    """Python 3.10 equivalent for the small integration read loop."""
    def __init__(self, seconds): self.seconds = seconds
    async def __aenter__(self):
        self.task = asyncio.current_task()
        self.handle = asyncio.get_running_loop().call_later(self.seconds, self.task.cancel)
    async def __aexit__(self, kind, value, traceback):
        self.handle.cancel()
        if kind is asyncio.CancelledError: raise TimeoutError("Terminal output timed out")


if __name__ == "__main__":
    unittest.main()
