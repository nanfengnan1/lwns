"""Opt-in Linux/root integration: FRR + veth + Web API + restore.

LWNS_CONFIG_DOCKER_TESTS=1 sudo -E .venv/bin/python -m unittest discover -s tests -p test_config_docker.py -v
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_core import LabManager
from lab_server import create_app


class ConfigDockerFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lwns-config-test-", dir=os.environ.get("LWNS_TEST_DIR"))
        self.manager = LabManager(self.temp.name)
        self.lab_id = "config-test-" + uuid.uuid4().hex[:10]
        self.manager.authorize()
        self.manager.save({"version": 1, "id": self.lab_id, "name": "FRR 配置恢复验证", "nodes": [
            {"id": "r1", "name": "R1", "kind": "router", "template": "frr", "image": "alpine/frr:latest",
             "x": 280, "y": 220, "ports": [{"name": "eth0", "address": "192.0.2.1/24"}], "config": "", "command": [], "gateway": ""},
            {"id": "pc1", "name": "PC1", "kind": "host", "template": "linux-host", "image": "alpine/vpcs:latest",
             "x": 520, "y": 220, "ports": [{"name": "eth0", "address": "192.0.2.2/24"}], "config": "", "command": [], "gateway": "192.0.2.1"},
        ], "links": [{"id": "l1", "a": {"node": "r1", "port": "eth0"}, "b": {"node": "pc1", "port": "eth0"}}]})

    def start(self):
        self.manager.deploy(self.manager.read(self.lab_id))

    def cleanup(self):
        try:
            self.manager.destroy(self.manager.read(self.lab_id))
            self.manager.delete(self.lab_id)
        finally:
            self.temp.cleanup()


@unittest.skipUnless(os.environ.get("LWNS_CONFIG_DOCKER_TESTS") == "1", "opt-in real FRR/veth persistence test")
class ConfigDockerTests(unittest.TestCase):
    def test_real_frr_api_save_cleanup_redeploy_and_connectivity(self):
        fixture = ConfigDockerFixture()
        self.addCleanup(fixture.cleanup)
        fixture.start()
        manager, lab_id = fixture.manager, fixture.lab_id
        record = manager.read(lab_id)
        cid = record["runtime"]["nodes"]["r1"]["id"]
        manager.dock("exec", cid, "vtysh", "-c", "configure terminal", "-c", "interface lo", "-c", "ip address 198.51.100.77/32",
                     "-c", "exit", "-c", "router ospf", "-c", "ospf router-id 203.0.113.77", "-c", "end")
        headers = {"Authorization": "Bearer config-integration", "Origin": "http://testserver"}
        with TestClient(create_app(manager, "config-integration")) as client:
            response = client.post(f"/api/labs/{lab_id}/configs", json={"node": "r1"}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()["results"][0]
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["status"]["shared"])
            self.assertIn("198.51.100.77/32", result["config"])
            folder = Path(result["status"]["path"])
            # Project save must capture subsequent live changes, not merely
            # return the configuration previously saved by the legacy endpoint.
            manager.dock("exec", cid, "vtysh", "-c", "configure terminal", "-c", "interface lo",
                         "-c", "description PROJECT_SAVED", "-c", "end")
            topology = manager.read(lab_id)["topology"]
            topology["nodes"][0]["x"] += 20
            saved = client.post(f"/api/labs/{lab_id}/save", json={"topology": topology}, headers=headers)
            self.assertEqual(saved.status_code, 200, saved.text)
            project = saved.json()
            self.assertTrue(project["topology_saved"])
            outcomes = {item["node"]: item for item in project["results"]}
            self.assertEqual(set(outcomes), {"r1", "pc1"})
            self.assertTrue(outcomes["r1"]["ok"], outcomes["r1"])
            self.assertTrue(outcomes["r1"]["status"]["shared"])
            self.assertIn("PROJECT_SAVED", outcomes["r1"]["config"])
            self.assertFalse(outcomes["pc1"]["ok"])
            self.assertTrue(outcomes["pc1"]["skipped"])
            self.assertEqual(project["record"]["runtime"]["deployment"], record["runtime"]["deployment"])
            self.assertEqual(project["record"]["runtime"]["nodes"], record["runtime"]["nodes"])
            self.assertEqual(project["record"]["topology"]["nodes"][0]["x"], topology["nodes"][0]["x"])
            self.assertIn("PROJECT_SAVED", project["record"]["topology"]["nodes"][0]["config"])
            before_close = manager.path(lab_id).read_bytes()
            closed = client.post(f"/api/labs/{lab_id}/close", json={}, headers=headers)
            self.assertEqual(closed.status_code, 200, closed.text)
            self.assertTrue(closed.json()["ok"])
            self.assertEqual(manager.path(lab_id).read_bytes(), before_close)
            opened = client.post(f"/api/labs/{lab_id}/open", json={}, headers=headers)
            self.assertEqual(opened.status_code, 200, opened.text)
            reopened = opened.json()
            self.assertEqual(reopened["topology"], project["record"]["topology"])
            self.assertEqual(reopened["runtime"]["deployment"], record["runtime"]["deployment"])
            self.assertEqual(reopened["runtime"]["nodes"], record["runtime"]["nodes"])
            self.assertEqual(reopened["runtime"]["phase"], "running")
        manager.destroy(manager.read(lab_id))
        self.assertIn("203.0.113.77", (folder / "frr.conf").read_text())
        self.assertIn("PROJECT_SAVED", (folder / "frr.conf").read_text())
        fixture.manager = manager = LabManager(fixture.temp.name)
        fixture.start()
        restored = manager.read(lab_id)
        next_cid = restored["runtime"]["nodes"]["r1"]["id"]
        self.assertNotEqual(cid, next_cid)
        self.assertIn("203.0.113.77", manager.dock("exec", next_cid, "vtysh", "-c", "show running-config"))
        self.assertIn("PROJECT_SAVED", manager.dock("exec", next_cid, "vtysh", "-c", "show running-config"))
        self.assertEqual(restored["topology"]["nodes"][0]["x"], topology["nodes"][0]["x"])
        self.assertIn("198.51.100.77", manager.ns(restored, "r1", "ip", "-4", "addr", "show", "lo"))
        self.assertEqual(manager.status(lab_id)["runtime"]["phase"], "running")
        host = restored["runtime"]["nodes"]["pc1"]["id"]
        self.assertIn("0% packet loss", manager.dock("exec", host, "ping", "-c", "2", "-W", "2", "192.0.2.1"))
        # A later terminal `write memory` must survive without a Web save too.
        manager.dock("exec", next_cid, "vtysh", "-c", "configure terminal", "-c", "interface lo", "-c", "description CLI_SAVED", "-c", "end", "-c", "write memory")
        manager.destroy(manager.read(lab_id))
        fixture.start()
        next_cid = manager.read(lab_id)["runtime"]["nodes"]["r1"]["id"]
        self.assertIn("CLI_SAVED", manager.dock("exec", next_cid, "vtysh", "-c", "show running-config"))


if __name__ == "__main__":
    unittest.main()
