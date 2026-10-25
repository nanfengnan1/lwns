"""Opt-in root/Linux test with two disposable Docker hosts and a real veth."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_capture import CaptureService
from lab_core import LabManager, LabError


class CaptureDockerFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lwns-capture-test-", dir=os.environ.get("LWNS_TEST_DIR"))
        self.manager = LabManager(self.temp.name)
        self.lab_id = "capture-test-" + uuid.uuid4().hex[:10]
        self.manager.authorize()
        self.manager.save({"version": 1, "id": self.lab_id, "name": "SSH 抓包验证", "nodes": [
            {"id": node, "name": node.upper(), "kind": "host", "image": "alpine/vpcs:latest", "template": "linux-host",
             "x": x, "y": 220, "ports": [{"name": "eth0", "address": ip}], "gateway": "", "config": "", "command": []}
            for node, x, ip in (("pc1", 250, "192.0.2.161/30"), ("pc2", 550, "192.0.2.162/30"))
        ], "links": [{"id": "wire1", "a": {"node": "pc1", "port": "eth0"}, "b": {"node": "pc2", "port": "eth0"}}]})

    def start(self):
        self.manager.deploy(self.manager.read(self.lab_id))

    def ping(self):
        cid = self.manager.read(self.lab_id)["runtime"]["nodes"]["pc1"]["id"]
        return self.manager.dock("exec", cid, "ping", "-c", "3", "-W", "1", "192.0.2.162")

    def cleanup(self):
        try:
            self.manager.destroy(self.manager.read(self.lab_id))
            self.manager.delete(self.lab_id)
        finally:
            self.temp.cleanup()


@unittest.skipUnless(os.environ.get("LWNS_CAPTURE_DOCKER_TESTS") == "1", "opt-in real veth capture test")
class CaptureDockerTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pcap_both_endpoints_filter_failure_and_stop(self):
        fixture = CaptureDockerFixture()
        self.addCleanup(fixture.cleanup)
        fixture.start()
        service = CaptureService(fixture.manager)
        self.addAsyncCleanup(service.close_lab)
        for side in ("a", "b"):
            issued = service.issue(fixture.lab_id, {"link": "wire1", "side": side, "filter": "icmp", "snaplen": 128})
            session = await service.open(service.claim(issued["ticket"])["stream_ticket"])
            data = bytearray()
            async def read():
                async for chunk in session.stream():
                    data.extend(chunk)
            reader = asyncio.create_task(read())
            self.assertIn("0% packet loss", await asyncio.to_thread(fixture.ping))
            await asyncio.sleep(0.2)
            await service.close_lab(fixture.lab_id, session.id)
            await reader
            path = Path(fixture.temp.name) / f"{side}.pcap"
            path.write_bytes(data)
            output = fixture.manager.run("tcpdump", "-nn", "-r", str(path))
            self.assertIn("192.0.2.161 > 192.0.2.162: ICMP echo request", output)
            self.assertIn("192.0.2.162 > 192.0.2.161: ICMP echo reply", output)
            self.assertIsNotNone(session.process.poll())
        issued = service.issue(fixture.lab_id, {"link": "wire1", "filter": "this is invalid BPF"})
        with self.assertRaises(LabError):
            await service.open(service.claim(issued["ticket"])["stream_ticket"])


if __name__ == "__main__":
    unittest.main()
