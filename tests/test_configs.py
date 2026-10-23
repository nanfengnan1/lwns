"""Persistent device configuration lifecycle, failure and HTTP coverage."""
import copy
from pathlib import Path
import tempfile
import unittest

from test_lab import FakeHost, example, LabError, LabManager, validate_topology
from lab_devices import adapter_for, device_root, template_for
from lab_server import create_app
from fastapi.testclient import TestClient


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.record = self.manager.save(example())
        self.node = self.record["topology"]["nodes"][0]
        self.root = device_root(self.manager, "first-lab", "r1")
        self.folder = self.root / "frr"

    def tearDown(self):
        self.temp.cleanup()

    def deploy(self):
        self.record = self.manager.read("first-lab")
        self.manager.deploy(self.record)
        self.cid = self.record["runtime"]["nodes"]["r1"]["id"]

    def test_old_topologies_and_explicit_templates(self):
        self.assertEqual(template_for(self.node)["id"], "frr")
        value = example()
        value["nodes"][0]["template"] = "frr"
        self.assertEqual(validate_topology(value)["nodes"][0]["template"], "frr")
        for name in ("linux-host", "missing", "../frr"):
            value["nodes"][0]["template"] = name
            with self.assertRaises(LabError):
                validate_topology(value)

    def test_save_cleanup_restart_restore_and_delete(self):
        self.deploy()
        mount = self.host.containers[self.cid]["Mounts"][0]
        self.assertEqual(mount["Destination"], "/etc/frr")
        self.assertTrue(mount["RW"])
        content = "hostname SAVED\ninterface lo\n ip address 198.51.100.7/32\n!\n"
        self.host.running_configs[self.cid] = content
        result = self.manager.save_configs("first-lab", "r1")["results"][0]
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["status"]["shared"])
        self.assertEqual((self.folder / "frr.conf").read_text(), content)
        self.assertEqual(self.manager.read("first-lab")["topology"]["nodes"][0]["config"], content.strip())
        self.assertEqual(len(list((self.root / "backups").iterdir())), 1)
        self.manager.destroy(self.manager.read("first-lab"))
        self.assertTrue((self.folder / "frr.conf").exists())
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.deploy()
        self.assertEqual(self.host.running_configs[self.cid], content)
        self.manager.destroy(self.manager.read("first-lab"))
        self.manager.delete("first-lab")
        self.assertFalse(self.root.exists())

    def test_cli_write_is_preserved_but_explicit_startup_edit_replaces_it(self):
        self.deploy()
        (self.folder / "frr.conf").write_text("hostname CLI_SAVED\n")
        self.manager.destroy(self.record)
        self.deploy()
        self.assertEqual(self.host.running_configs[self.cid], "hostname CLI_SAVED\n")
        self.manager.destroy(self.record)
        topology = self.manager.read("first-lab")["topology"]
        topology["nodes"][0]["config"] = "hostname EDITED"
        self.manager.save(topology)
        self.deploy()
        self.assertEqual(self.host.running_configs[self.cid], "hostname EDITED\n")
        self.assertTrue(any((path / "frr.conf").read_text() == "hostname CLI_SAVED\n" for path in (self.root / "backups").iterdir()))

    def test_missing_daemon_or_save_failure_keeps_previous_file(self):
        self.deploy()
        original = (self.folder / "frr.conf").read_text()
        self.host.running_configs[self.cid] = "hostname NEW\n"
        self.host.live_daemons = "zebra bgpd ospfd"
        result = self.manager.save_configs("first-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("ospf6d", result["error"])
        self.assertEqual((self.folder / "frr.conf").read_text(), original)
        self.host.live_daemons += " ospf6d staticd mgmtd"
        self.host.save_error = True
        self.assertFalse(self.manager.save_configs("first-lab", "r1")["results"][0]["ok"])
        self.assertEqual((self.folder / "frr.conf").read_text(), original)

    def test_always_on_staticd_and_mgmtd_are_required_before_save(self):
        self.deploy()
        for daemon in ("staticd", "mgmtd"):
            with self.subTest(daemon=daemon):
                original = self.host.live_daemons
                self.host.live_daemons = original.replace(daemon, "")
                result = self.manager.save_configs("first-lab", "r1")["results"][0]
                self.assertFalse(result["ok"])
                self.assertIn(daemon, result["error"])
                self.host.live_daemons = original

    def test_mount_ownership_stopped_and_oversized_configs_are_rejected(self):
        self.deploy()
        item = self.host.containers[self.cid]
        item["Mounts"][0]["RW"] = False
        self.assertIn("挂载", self.manager.save_configs("first-lab", "r1")["results"][0]["error"])
        item["Mounts"][0]["RW"] = True
        item["Config"]["Labels"]["io.route-ovs.lab"] = "foreign"
        self.assertFalse(self.manager.save_configs("first-lab", "r1")["results"][0]["ok"])
        item["Config"]["Labels"]["io.route-ovs.lab"] = "first-lab"
        item["State"]["Running"] = False
        self.assertFalse(self.manager.save_configs("first-lab", "r1")["results"][0]["ok"])
        item["State"]["Running"] = True
        self.host.running_configs[self.cid] = "!" * 32769
        self.assertIn("上限", self.manager.save_configs("first-lab", "r1")["results"][0]["error"])

    def test_no_deployment_busy_and_unsupported_template(self):
        with self.assertRaisesRegex(LabError, "尚未部署"):
            self.manager.save_configs("first-lab")
        self.deploy()
        self.manager.busy = "other-lab"
        with self.assertRaisesRegex(LabError, "进行中"):
            self.manager.save_configs("first-lab")
        self.manager.busy = None
        result = self.manager.save_configs("first-lab", "pc1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertFalse(self.manager.configs("first-lab", "pc1")["pc1"]["supported"])

    def test_legacy_device_can_export_before_redeployment(self):
        self.deploy()
        self.host.containers[self.cid]["Mounts"] = []
        self.host.running_configs[self.cid] = "hostname LEGACY\n"
        result = self.manager.save_configs("first-lab", "r1")["results"][0]
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["status"]["shared"])
        self.manager.destroy(self.manager.read("first-lab"))
        self.deploy()
        self.assertEqual(self.host.running_configs[self.cid], "hostname LEGACY\n")

    def test_partial_save_preserves_successful_devices(self):
        topology = example()
        second = copy.deepcopy(topology["nodes"][0])
        second.update(id="r2", name="R2")
        for port in second["ports"]:
            port["address"] = ""
        topology["nodes"].append(second)
        self.manager.save(topology)
        self.deploy()
        second_cid = self.record["runtime"]["nodes"]["r2"]["id"]
        self.host.containers[second_cid]["State"]["Running"] = False
        result = self.manager.save_configs("first-lab")["results"]
        self.assertEqual([(item["node"], item["ok"]) for item in result], [("r1", True), ("r2", False)])
        self.assertTrue(self.manager.configs("first-lab", "r1")["r1"]["saved_at"])

    def test_paths_and_symlinks_do_not_escape_data_directory(self):
        with self.assertRaises(LabError):
            device_root(self.manager, "../outside")
        self.root.mkdir(parents=True)
        self.folder.symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaises(LabError):
            self.manager.configs("first-lab")
        self.folder.unlink()

    def test_config_api_auth_and_disk_status(self):
        self.deploy()
        with TestClient(create_app(self.manager, "config-token")) as client:
            url = "/api/labs/first-lab/configs"
            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.post(url, json={}).status_code, 401)
            headers = {"Authorization": "Bearer config-token"}
            self.assertEqual(client.post(url, json={}, headers={**headers, "Origin": "http://foreign.invalid"}).status_code, 403)
            response = client.post(url, json={"node": "r1"}, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["results"][0]["ok"])
            response = client.get(url + "/r1", headers=headers)
            self.assertTrue(response.json()["r1"]["persisted"])
            self.assertEqual(client.get(url + "/missing", headers=headers).status_code, 400)


if __name__ == "__main__":
    unittest.main()
