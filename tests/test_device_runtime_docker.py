"""Opt-in root/Linux test of packaged native and FRR save/restore lifecycles.

LWNS_DEVICE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_device_runtime_docker.py -v
Only uniquely named, isolated projects and their containers are created. Images
are referenced by immutable ID and are never pulled, rebuilt, tagged or removed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_core import LabError, LabManager
from lab_device_packages import pack_device
from test_device_runtime import descriptor, node


@unittest.skipUnless(os.environ.get("LWNS_DEVICE_DOCKER_TESTS") == "1", "opt-in real device package save/restore test")
class DeviceRuntimeDockerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lwns-device-runtime-test-", dir=os.environ.get("LWNS_TEST_DIR"))
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.manager = LabManager(self.directory / "data")
        self.manager.authorize()
        self.lab_id = "device-test-" + uuid.uuid4().hex[:12]
        self.addCleanup(self.cleanup_project)

    def cleanup_project(self):
        if self.manager.path(self.lab_id).exists():
            record = self.manager.read(self.lab_id)
            self.manager.destroy(record)
            self.manager.delete(self.lab_id)

    def install(self, definition):
        try:
            image = json.loads(self.manager.dock("image", "inspect", definition["image"]))[0]["Id"]
        except (LabError, ValueError, IndexError, KeyError) as exc:
            self.skipTest("required local image unavailable: " + str(exc))
        path = self.directory / "device.lwns"
        pack_device(definition, path)
        entry = self.manager.device_library.register(path, image_id=image)
        return entry["id"], image

    def project(self, definition, two=False):
        template, image = self.install(definition)
        nodes = [node("r1", template)]
        links = []
        if two:
            nodes.append(node("r2", template))
            nodes[0]["ports"][0]["address"] = "198.18.0.1/30"
            nodes[1]["ports"][0]["address"] = "198.18.0.2/30"
            links.append({"id": "l1", "a": {"node": "r1", "port": "eth0"}, "b": {"node": "r2", "port": "eth0"}})
        for item in nodes:
            item["image"] = image
        self.manager.save({"version": 1, "id": self.lab_id, "name": "Isolated .lwns runtime test", "nodes": nodes, "links": links})
        self.manager.deploy(self.manager.read(self.lab_id))
        return self.manager.read(self.lab_id)

    def test_generic_two_instances_execute_service_save_and_restore(self):
        definition = descriptor()
        definition["persistent_dirs"] = [{"id": "native", "target": "/etc/rov-test", "initialize_from": "empty", "owner": "0:0"}]
        definition["startup"] = {
            "phase": "after_links",
            "prepare": [{"exec": ["sh", "-c", "test -s /etc/rov-test/startup.conf || printf 'initial\\n' > /etc/rov-test/startup.conf"]}],
            "service": {"exec": ["sh", "-c", "cp /etc/rov-test/startup.conf /run/rov-runtime.conf; exec sleep infinity"]},
            "config_files": ["/etc/rov-test/startup.conf"],
            "ready": {"exec": ["sh", "-c", "test -s /run/rov-runtime.conf"], "timeout_seconds": 10}}
        definition["actions"] = {"save_config": {"exec": ["sh", "-c", "cp /run/rov-runtime.conf /etc/rov-test/startup.conf"]}}
        record = self.project(definition, two=True)
        old = {key: value["id"] for key, value in record["runtime"]["nodes"].items()}
        for name, cid in old.items():
            current = self.manager.dock("exec", cid, "cat", "/run/rov-runtime.conf")
            self.assertEqual(current, "initial")
            self.manager.dock("exec", cid, "sh", "-c", 'printf "%s\\n" "$1" > /run/rov-runtime.conf', "set-native", name + "-saved")
            # The supervised main process has exec'd the declared service.
            self.assertEqual(self.manager.dock("exec", cid, "sh", "-c",
                             'cat "/proc/$(cat /run/route-ovs-state/service.pid)/comm"'), "sleep")
        self.assertIn("0% packet loss", self.manager.dock("exec", old["r1"], "ping", "-c", "1", "-W", "2", "198.18.0.2"))
        saved = self.manager.save_project(record["topology"])
        self.assertTrue(all(row["ok"] for row in saved["results"]), saved)
        self.manager.destroy(self.manager.read(self.lab_id))
        self.manager = LabManager(self.manager.directory)
        self.manager.deploy(self.manager.read(self.lab_id))
        restored = self.manager.read(self.lab_id)
        for name, value in restored["runtime"]["nodes"].items():
            self.assertNotEqual(value["id"], old[name])
            self.assertEqual(self.manager.dock("exec", value["id"], "cat", "/run/rov-runtime.conf"), name + "-saved")
        self.assertEqual(self.manager.status(self.lab_id)["runtime"]["phase"], "running")

    def test_packaged_frr_preserves_daemons_and_native_configuration(self):
        record = self.project(descriptor("frr"))
        cid = record["runtime"]["nodes"]["r1"]["id"]
        self.manager.dock("exec", cid, "vtysh", "-c", "configure terminal", "-c", "interface lo",
                          "-c", "ip address 198.51.100.91/32", "-c", "exit", "-c", "router ospf",
                          "-c", "ospf router-id 203.0.113.91", "-c", "end")
        result = self.manager.save_configs(self.lab_id, "r1")["results"][0]
        self.assertTrue(result["ok"], result)
        self.assertIn("203.0.113.91", result["config"])
        folder = Path(result["status"]["path"])
        self.assertTrue(all((folder / name).is_file() for name in ("frr.conf", "daemons", "vtysh.conf")))
        self.manager.destroy(self.manager.read(self.lab_id))
        self.manager = LabManager(self.manager.directory)
        self.manager.deploy(self.manager.read(self.lab_id))
        next_cid = self.manager.read(self.lab_id)["runtime"]["nodes"]["r1"]["id"]
        self.assertNotEqual(cid, next_cid)
        restored = self.manager.dock("exec", next_cid, "vtysh", "-c", "show running-config")
        self.assertIn("203.0.113.91", restored)
        self.assertIn("198.51.100.91/32", restored)


if __name__ == "__main__":
    unittest.main()
