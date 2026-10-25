"""Incremental update tests use modeled containers and namespace interfaces only."""
import copy
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import test_lab as fixtures
from lab_core import LABEL, LabError


class TopologyUpdateTests(unittest.TestCase):
    def setUp(self):
        fixtures.DeploymentTests.setUp(self)
        self.manager.deploy(self.record)
        self.original = copy.deepcopy(self.record)
        self.host.calls.clear()

    def tearDown(self):
        self.temp.cleanup()

    def target(self):
        return copy.deepcopy(self.original["topology"])

    def apply(self, target):
        self.manager.update(self.record, target)
        return self.manager.read("first-lab")

    def assert_unchanged_containers(self):
        self.assertEqual(self.record["runtime"]["nodes"], self.original["runtime"]["nodes"])

    def test_incremental_address_preserves_containers_and_manual_addresses(self):
        target = self.target()
        target["nodes"][3]["ports"][0]["address"] = "10.10.1.20/24"
        cid = self.record["runtime"]["nodes"]["pc1"]["id"]
        self.host.interfaces[cid]["eth0"]["addr_info"].append({"local": "192.0.2.1", "prefixlen": 24})
        self.apply(target)
        self.assert_unchanged_containers()
        addresses = {a["local"] for a in self.host.interfaces[cid]["eth0"]["addr_info"]}
        self.assertEqual(addresses, {"10.10.1.20", "192.0.2.1"})
        self.assertFalse(any("flush" in args or "vtysh" in args for args, _ in self.host.calls))

    def test_remove_and_reconnect_link_keeps_disconnected_address_and_gateway(self):
        target = self.target(); target["links"] = target["links"][:-1]
        after = self.apply(target)
        self.assert_unchanged_containers()
        cid = after["runtime"]["nodes"]["pc2"]["id"]
        self.assertNotIn("eth0", self.host.interfaces[cid])
        self.assertEqual(after["topology"]["nodes"][4]["ports"][0]["address"], "10.10.2.10/24")
        self.apply(self.target())
        self.assertIn("eth0", self.host.interfaces[cid])
        self.assertEqual(self.host.routes[cid][0]["gateway"], "10.10.2.1")

    def test_add_and_remove_device_preserves_other_containers(self):
        target = self.target()
        target["nodes"].append(dict(copy.deepcopy(target["nodes"][4]), id="pc3", name="PC3", gateway="", ports=[{"name":"eth0", "address":""}]))
        target["links"].append({"id":"new-link", "a":{"node":"sw2", "port":"eth2"}, "b":{"node":"pc3", "port":"eth0"}})
        self.apply(target)
        for nid, saved in self.original["runtime"]["nodes"].items():
            self.assertEqual(self.record["runtime"]["nodes"][nid], saved)
        self.assertEqual(len(self.host.containers), 6)
        self.apply(self.target())
        self.assert_unchanged_containers()
        self.assertEqual(len(self.host.containers), 5)

    def test_changed_startup_rebuilds_only_that_device_and_its_links(self):
        target = self.target(); target["nodes"][4]["command"] = ["sleep", "10000"]
        r1 = self.original["runtime"]["nodes"]["r1"]["id"]
        self.host.running_configs[r1] = "hostname CLI-UNSAVED\n"
        self.apply(target)
        for nid in ("r1", "sw1", "sw2", "pc1"):
            self.assertEqual(self.record["runtime"]["nodes"][nid], self.original["runtime"]["nodes"][nid])
        self.assertNotEqual(self.record["runtime"]["nodes"]["pc2"]["id"], self.original["runtime"]["nodes"]["pc2"]["id"])
        self.assertEqual(self.host.running_configs[r1], "hostname CLI-UNSAVED\n")

    def test_empty_topology_removes_all_resources_but_keeps_deployment_identity(self):
        target = dict(self.target(), nodes=[], links=[])
        self.apply(target)
        self.assertEqual(self.host.containers, {})
        self.assertEqual(self.record["runtime"]["deployment"], self.original["runtime"]["deployment"])
        self.assertEqual(self.record["runtime"]["phase"], "running")
        self.manager.destroy(self.record)
        self.assertNotIn("deployment", self.record["runtime"])

    def test_visual_and_annotation_save_never_calls_host(self):
        target = self.target(); target["nodes"][0]["x"] += 77
        target["annotations"] = [{"id":"note-1", "text":"online note", "x":0, "y":0}]
        target["name"] = "New project title"
        after = self.manager.save(target)
        self.assertEqual(self.host.calls, [])
        self.assertEqual(after["runtime"], self.original["runtime"])

    def test_preflight_rejects_foreign_veth_and_node_labels_without_mutation(self):
        for violation in ("alias", "peer", "type", "node-label"):
            with self.subTest(violation=violation):
                cid = self.original["runtime"]["nodes"]["pc2"]["id"]
                row = self.host.interfaces[cid]["eth0"]
                saved = copy.deepcopy(row)
                if violation == "alias": row["ifalias"] = "foreign"
                if violation == "peer": row["link_index"] += 100
                if violation == "type": row["linkinfo"] = {"info_kind":"dummy"}
                if violation == "node-label": self.host.containers[cid]["Config"]["Labels"][LABEL+".node"] = "other"
                self.host.calls.clear()
                target = self.target(); target["links"] = target["links"][:-1]
                with self.assertRaises(LabError): self.apply(target)
                self.assertEqual(self.manager.read("first-lab"), self.original)
                self.assertFalse(any("delete" in args or "rm" in args or "create" in args for args, _ in self.host.calls))
                self.host.interfaces[cid]["eth0"] = saved
                self.host.containers[cid]["Config"]["Labels"][LABEL+".node"] = "pc2"

    def test_preflight_rejects_unmanaged_interface_name_and_missing_image(self):
        cid = self.record["runtime"]["nodes"]["r1"]["id"]
        self.host.interfaces[cid]["eth2"] = {"ifname":"eth2", "ifindex":500, "linkinfo":{"info_kind":"dummy"}}
        target = self.target()
        target["links"].append({"id":"new", "a":{"node":"r1", "port":"eth2"}, "b":{"node":"sw1", "port":"eth2"}})
        with self.assertRaisesRegex(LabError, "占用"): self.apply(target)
        target = self.target(); target["nodes"][4]["image"] = "missing:latest"
        self.host.missing_image = True
        with self.assertRaisesRegex(LabError, "镜像"): self.apply(target)
        self.assert_unchanged_containers()

    def test_link_creation_failure_recovers_original_links_without_restarting_peers(self):
        target = self.target(); target["links"][-1]["a"]["port"] = "eth2"
        self.host.fail_link = True
        with self.assertRaisesRegex(LabError, "原拓扑保留"): self.apply(target)
        self.assertEqual(self.record["topology"], self.original["topology"])
        self.assert_unchanged_containers()
        self.assertEqual(self.manager.status("first-lab")["runtime"]["phase"], "running")

    def test_partial_new_link_alias_failure_removes_only_recorded_new_pair(self):
        target = self.target()
        target["links"].append({"id":"new", "a":{"node":"r1", "port":"eth2"}, "b":{"node":"sw1", "port":"eth2"}})
        original = self.manager.ns
        def fail_alias(record, nid, *args):
            if "alias" in args and args[-1].endswith(":new:b"):
                raise LabError("alias failed")
            return original(record, nid, *args)
        with patch.object(self.manager, "ns", side_effect=fail_alias), self.assertRaisesRegex(LabError, "原拓扑保留"):
            self.apply(target)
        self.assertNotIn("eth2", self.host.interfaces[self.record["runtime"]["nodes"]["r1"]["id"]])
        self.assert_unchanged_containers()

    def test_rebuild_failure_restores_previous_frr_files_and_other_containers(self):
        target = self.target(); target["nodes"][0]["config"] = "hostname NEW\n"
        root = Path(self.temp.name)/"devices"/"first-lab"/"r1"/"frr"
        before = (root/"frr.conf").read_bytes()
        self.host.fail_link = True
        with self.assertRaisesRegex(LabError, "原拓扑保留"): self.apply(target)
        self.assertEqual((root/"frr.conf").read_bytes(), before)
        for nid in ("sw1", "sw2", "pc1", "pc2"):
            self.assertEqual(self.record["runtime"]["nodes"][nid], self.original["runtime"]["nodes"][nid])
        self.assertEqual(self.record["topology"], self.original["topology"])

    def test_config_recovery_does_not_write_through_container_created_symlink(self):
        target = self.target(); target["nodes"][0]["config"] = "hostname NEW\n"
        config = Path(self.temp.name)/"devices"/"first-lab"/"r1"/"frr"/"frr.conf"
        original_config = config.read_bytes()
        outside = Path(self.temp.name)/"outside.txt"; outside.write_text("untouched")
        original_runner = self.manager.runner
        changed = False
        def substitute(argv, **kwargs):
            nonlocal changed
            if argv[:3] == ["ip", "link", "add"] and not changed:
                changed = True
                config.unlink(); config.symlink_to(outside)
                raise LabError("failure after container replaced shared config")
            return original_runner(argv, **kwargs)
        self.manager.runner = substitute
        with self.assertRaisesRegex(LabError, "原拓扑保留"): self.apply(target)
        self.assertEqual(outside.read_text(), "untouched")
        self.assertFalse(config.is_symlink())
        self.assertEqual(config.read_bytes(), original_config)

    def test_failed_cleanup_retains_added_container_for_explicit_destroy(self):
        target = self.target()
        target["nodes"].append(dict(copy.deepcopy(target["nodes"][4]), id="pc3", name="PC3", gateway="", ports=[{"name":"eth0", "address":""}]))
        target["links"].append({"id":"new-link", "a":{"node":"sw2", "port":"eth2"}, "b":{"node":"pc3", "port":"eth0"}})
        self.host.fail_link = True
        self.host.fail_remove = True
        self.manager._update_job(self.record, target)
        record = self.manager.read("first-lab")
        self.assertEqual(record["topology"], self.original["topology"])
        self.assertEqual(record["runtime"]["phase"], "error")
        self.assertIn("pc3", record["runtime"]["nodes"])
        self.assertIn("恢复未完成", record["runtime"]["error"])
        self.host.fail_remove = False
        self.manager.destroy(record)
        self.assertFalse(self.host.containers)

    def test_base_conflict_and_invalid_body_have_no_host_calls(self):
        base = self.target(); base["name"] = "stale"
        for payload in ({}, {"topology":self.target(), "base":base}, {"topology":dict(self.target(), id="wrong"), "base":self.target()}):
            with self.assertRaises(LabError): self.manager.start_update("first-lab", payload)
        self.assertEqual(self.host.calls, [])
        self.assertIsNone(self.manager.busy)

    def test_background_update_holds_lock_and_returns_detached_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        original = self.manager.update
        def blocked(record, target):
            entered.set(); release.wait(5); original(record, target)
        target = self.target(); target["nodes"][4]["ports"][0]["address"] = "10.10.2.20/24"
        with patch.object(self.manager, "update", side_effect=blocked):
            response = self.manager.start_update("first-lab", {"topology":target, "base":self.target()})
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(response["runtime"]["phase"], "updating")
                self.assertEqual(response["topology"], self.original["topology"])
                with self.assertRaises(LabError): self.manager.save(self.target())
                with self.assertRaises(LabError): self.manager.start_job("first-lab", "destroy")
            finally:
                release.set()
                for thread in threading.enumerate():
                    if thread.name == "lab-update-first-lab": thread.join(5)
        self.assertEqual(self.manager.read("first-lab")["runtime"]["phase"], "running")
        self.assertEqual(response["runtime"]["phase"], "updating")
        self.assertIsNone(self.manager.busy)

    def test_failed_worker_keeps_old_topology_and_allows_cleanup(self):
        target = self.target(); target["links"][-1]["a"]["port"] = "eth2"
        self.host.fail_link = True
        self.manager._update_job(self.record, target)
        record = self.manager.read("first-lab")
        self.assertEqual(record["runtime"]["phase"], "error")
        self.assertEqual(record["topology"], self.original["topology"])
        with self.assertRaises(LabError): self.manager.start_update("first-lab", {"topology":target, "base":self.target()})
        self.manager.destroy(record)
        self.assertFalse(self.host.containers)


if __name__ == "__main__":
    unittest.main()
