"""Descriptor lifecycle contracts; no real Docker or namespace mutations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_core import LabError, LabManager
from lab_device_packages import pack_device
from lab_device_runtime import BOOTSTRAP, EXECUTED, configuration_files
from lab_device_service import DevicePackageService
from test_lab import FakeHost


IMAGE_ID = "sha256:" + "4" * 64


def descriptor(profile="generic"):
    if profile == "frr":
        return {"schema_version": 1, "id": "test-frr", "version": "1.0.0", "name": "FRR",
                "category": "router", "image": "alpine/frr:latest", "source": {"type": "repository"},
                "profile": "frr", "console": ["vtysh"],
                "persistent_dirs": [{"id": "frr", "target": "/etc/frr", "initialize_from": "image"}],
                "startup": {"phase": "after_links", "service": {"exec": ["/usr/lib/frr/docker-start"]},
                            "config_files": ["/etc/frr/frr.conf", "/etc/frr/daemons", "/etc/frr/vtysh.conf"]},
                "actions": {"save_config": {"exec": ["vtysh", "-w"]}}}
    return {"schema_version": 1, "id": "test-native", "version": "1.0.0", "name": "Native router",
            "category": "router", "image": "alpine/vpcs:latest", "source": {"type": "repository"},
            "profile": "generic", "console": ["sh", "-i"],
            "persistent_dirs": [{"id": "native", "target": "/etc/native", "initialize_from": "empty", "owner": f"{os.getuid()}:{os.getgid()}"}],
            "startup": {"phase": "after_links", "prepare": [{"exec": ["prepare-native"]}],
                        "service": {"exec": ["serve-native"]}, "config_files": ["/etc/native/settings.conf"],
                        "ready": {"exec": ["check-native"], "contains": ["native ready"], "timeout_seconds": 1, "interval_seconds": 0.1}},
            "actions": {"save_config": {"exec": ["save-native"], "contains": ["saved"]},
                        "after_link_added": {"exec": ["link-added"]}}}


def node(identity, template, kind="router"):
    return {"id": identity, "name": identity.upper(), "kind": kind, "template": template,
            "image": IMAGE_ID, "ports": [{"name": "eth0", "address": ""}, {"name": "eth1", "address": ""}],
            "command": [], "config": "", "gateway": "", "x": 100, "y": 100}


class NativeHost(FakeHost):
    def __init__(self):
        super().__init__()
        self.native = {}
        self.prepare_ports = {}
        self.action_calls = []
        self.fail_native_save = False
        self.skip_native_write = False
        self.fail_prepare_once = False

    def __call__(self, argv, **kwargs):
        args = argv[3:] if argv[0] == "docker" else []
        if args[:1] == ["cp"]:
            self.calls.append((argv, kwargs))
            Path(args[-1], "settings.conf").write_text("image seed\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if args[:1] == ["exec"]:
            index = next((i for i, arg in enumerate(args) if arg in self.containers), None)
            if index is not None:
                cid, command = args[index], args[index + 1:]
                item = self.containers[cid]
                native = next((Path(m["Source"]) for m in item.get("Mounts", []) if m["Destination"] == "/etc/native"), None)
                control = next((Path(m["Source"]) for m in item.get("Mounts", []) if m["Destination"] == "/run/route-ovs"), None)
                if native and (command in (["prepare-native"], ["check-native"], ["save-native"], ["link-added"])
                               or command == ["/bin/sh", "-c", EXECUTED]):
                    self.calls.append((argv, kwargs))
                    self.action_calls.append((cid, command))
                    output = ""
                    if command == ["prepare-native"]:
                        if self.fail_prepare_once:
                            self.fail_prepare_once = False
                            raise LabError("native preparation failed")
                        if control.joinpath("start").exists():
                            raise AssertionError("service released before prepare")
                        self.prepare_ports[cid] = set(self.interfaces[cid])
                        if not (native / "settings.conf").exists():
                            (native / "settings.conf").write_text("default\n")
                    elif command == ["/bin/sh", "-c", EXECUTED]:
                        if not control.joinpath("start").exists():
                            raise LabError("bootstrap has not executed service")
                        self.native.setdefault(cid, (native / "settings.conf").read_text())
                    elif command == ["check-native"]:
                        if cid not in self.native:
                            raise LabError("native service not ready")
                        output = "native ready"
                    elif command == ["save-native"]:
                        if self.fail_native_save:
                            raise LabError("native save failed")
                        if not self.skip_native_write:
                            (native / "settings.conf").write_text(self.native[cid])
                        output = "saved"
                    return subprocess.CompletedProcess(argv, 0, output, "")
        return super().__call__(argv, **kwargs)


class DeviceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.host = NativeHost()
        self.manager = LabManager(self.directory / "data", runner=self.host)
        self.manager.authorize = lambda: None

    def install(self, definition=None):
        definition = definition or descriptor()
        path = self.directory / (definition["id"] + ".lwns")
        pack_device(definition, path)
        return self.manager.device_library.register(path, image_id=IMAGE_ID)["id"]

    def lab(self, definition=None):
        definition = definition or descriptor()
        template = self.install(definition)
        topology = {"version": 1, "id": "native-lab", "name": "Native lab",
                    "nodes": [node("r1", template, definition["category"]), node("r2", template, definition["category"])],
                    "links": [{"id": "l1", "a": {"node": "r1", "port": "eth0"}, "b": {"node": "r2", "port": "eth0"}}]}
        self.manager.save(topology)
        self.manager.deploy(self.manager.read("native-lab"))
        return self.manager.read("native-lab")

    def test_native_save_cleanup_restart_preserves_separate_instance_files(self):
        record = self.lab()
        ids = {n: v["id"] for n, v in record["runtime"]["nodes"].items()}
        for name, cid in ids.items():
            self.assertIn("eth0", self.host.prepare_ports[cid])
            self.host.native[cid] = name + " saved settings\n"
        saved = self.manager.save_project(record["topology"])
        self.assertTrue(all(row["ok"] for row in saved["results"]), saved)
        for row in saved["results"]:
            self.assertEqual(row["status"]["files"], [{"path": "/etc/native/settings.conf", "size": len(row["node"] + " saved settings\n")}])
            self.assertTrue(row["status"]["shared"])
        self.manager.destroy(self.manager.read("native-lab"))
        self.manager = LabManager(self.manager.directory, runner=self.host)
        self.manager.authorize = lambda: None
        self.manager.deploy(self.manager.read("native-lab"))
        restored = self.manager.read("native-lab")
        for name, value in restored["runtime"]["nodes"].items():
            self.assertNotEqual(value["id"], ids[name])
            self.assertEqual(self.host.native[value["id"]], name + " saved settings\n")

    def test_seed_copied_once_and_default_not_reapplied(self):
        definition = descriptor()
        definition["persistent_dirs"][0]["initialize_from"] = "image"
        record = self.lab(definition)
        count = sum(call[0][3:4] == ["cp"] for call in self.host.calls)
        self.assertEqual(count, 2)
        for value in record["runtime"]["nodes"].values():
            self.assertEqual(self.host.native[value["id"]], "image seed\n")
        self.manager.destroy(record)
        self.manager.deploy(self.manager.read("native-lab"))
        self.assertEqual(sum(call[0][3:4] == ["cp"] for call in self.host.calls), count)
        self.assertFalse(any(item["Name"].startswith("/rov-seed-") for item in self.host.containers.values()))

    def test_switch_category_does_not_create_linux_bridge(self):
        definition = descriptor()
        definition["category"] = "switch"
        self.lab(definition)
        self.assertFalse(any("br0" in argv for argv, _ in self.host.calls))

    def test_image_and_start_command_cannot_override_definition(self):
        template = self.install()
        topology = {"version": 1, "id": "test", "name": "test", "nodes": [node("r1", template)], "links": []}
        topology["nodes"][0]["image"] = "unrelated:latest"
        with self.assertRaisesRegex(LabError, "镜像已固定"):
            self.manager.save(topology)
        topology["nodes"][0]["image"] = IMAGE_ID
        topology["nodes"][0]["command"] = ["sh"]
        with self.assertRaisesRegex(LabError, "启动流程已固定"):
            self.manager.save(topology)

    def test_project_validation_and_persistence_hold_definition_deletion_lock(self):
        template = self.install()
        service = DevicePackageService(self.manager)
        topology = {"version": 1, "id": "new-project", "name": "New", "nodes": [node("r1", template)], "links": []}
        validated, probed = threading.Event(), threading.Event()
        original = self.manager.validate
        failures, removals, lock_probe = [], [], []

        def validate(value):
            normalized = original(value)
            if not validated.is_set():
                validated.set()
                if not probed.wait(5):
                    raise AssertionError("deletion probe did not run")
            return normalized

        def save():
            try:
                self.manager.save(topology)
            except Exception as exc:
                failures.append(exc)

        def remove():
            if not validated.wait(5):
                failures.append(AssertionError("save did not validate"))
                probed.set()
                return
            acquired = self.manager.lock.acquire(blocking=False)
            lock_probe.append(acquired)
            if acquired:
                self.manager.lock.release()
            probed.set()
            try:
                service.remove(template)
                removals.append("removed")
            except LabError as exc:
                removals.append(str(exc))

        self.manager.validate = validate
        saver, remover = threading.Thread(target=save), threading.Thread(target=remove)
        saver.start()
        remover.start()
        saver.join(10)
        remover.join(10)
        self.assertFalse(saver.is_alive() or remover.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(lock_probe, [False], "definition resolution must happen under manager lock")
        self.assertIn("项目引用", removals[0])
        self.assertEqual(self.manager.read("new-project")["topology"]["nodes"][0]["template"], template)

    def test_foreign_or_readonly_mount_refuses_save_before_command(self):
        record = self.lab()
        cid = record["runtime"]["nodes"]["r1"]["id"]
        mount = next(m for m in self.host.containers[cid]["Mounts"] if m["Destination"] == "/etc/native")
        before = len([row for row in self.host.action_calls if row == (cid, ["save-native"])])
        mount["RW"] = False
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("挂载", result["error"])
        self.assertEqual(len([row for row in self.host.action_calls if row == (cid, ["save-native"])]), before)

    def test_save_failure_retains_backup_and_does_not_mark_saved(self):
        self.lab()
        self.host.fail_native_save = True
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        root = self.manager.directory / "devices" / "native-lab" / "r1"
        self.assertTrue(list((root / "backups").glob("*/native/settings.conf")))
        self.assertIsNone(self.manager.configs("native-lab", "r1")["r1"]["saved_at"])

    def test_missing_expected_file_is_not_a_successful_save(self):
        record = self.lab()
        self.host.skip_native_write = True
        folder = self.manager.directory / "devices" / "native-lab" / "r1" / "native"
        (folder / "settings.conf").unlink()
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("必要配置文件", result["error"])

    def test_incremental_link_hook_does_not_restart_unchanged_service(self):
        record = self.lab()
        old_id = record["runtime"]["nodes"]["r1"]["id"]
        template = record["topology"]["nodes"][0]["template"]
        target = copy.deepcopy(record["topology"])
        target["nodes"].append(node("r3", template))
        target["links"].append({"id": "l2", "a": {"node": "r1", "port": "eth1"}, "b": {"node": "r3", "port": "eth0"}})
        self.manager.update(record, target)
        updated = self.manager.read("native-lab")
        self.assertEqual(updated["runtime"]["nodes"]["r1"]["id"], old_id)
        self.assertEqual(self.host.action_calls.count((old_id, ["prepare-native"])), 1)
        self.assertEqual(self.host.action_calls.count((old_id, ["link-added"])), 1)

    def test_failed_rebuild_restores_native_files_and_releases_new_bootstrap(self):
        record = self.lab()
        old_r1 = record["runtime"]["nodes"]["r1"]["id"]
        old_r2 = record["runtime"]["nodes"]["r2"]["id"]
        self.host.native[old_r1] = "persist before rebuild\n"
        self.assertTrue(self.manager.save_configs("native-lab", "r1")["results"][0]["ok"])
        record = self.manager.read("native-lab")
        target = copy.deepcopy(record["topology"])
        target["nodes"][0]["name"] = "CHANGED"
        self.host.fail_prepare_once = True
        with self.assertRaisesRegex(LabError, "native preparation failed"):
            self.manager.update(record, target)
        restored = self.manager.read("native-lab")
        self.assertEqual(restored["topology"]["nodes"][0]["name"], "R1")
        new_r1 = restored["runtime"]["nodes"]["r1"]["id"]
        self.assertNotEqual(new_r1, old_r1)
        self.assertEqual(restored["runtime"]["nodes"]["r2"]["id"], old_r2)
        self.assertEqual(self.host.native[new_r1], "persist before rebuild\n")
        self.assertIn("eth0", self.host.prepare_ports[new_r1])

    def test_container_phase_prepares_before_links(self):
        definition = descriptor()
        definition["startup"]["phase"] = "container"
        record = self.lab(definition)
        for value in record["runtime"]["nodes"].values():
            self.assertEqual(self.host.prepare_ports[value["id"]], {"lo"})
            self.assertIn("eth0", self.host.interfaces[value["id"]])

    def test_instance_directory_cannot_be_reused_for_different_definition(self):
        record = self.lab()
        self.manager.destroy(record)
        newer = descriptor()
        newer["version"] = "2.0.0"
        newer["id"] = "other-native"
        template = self.install(newer)
        record = self.manager.read("native-lab")
        record["topology"]["nodes"][0]["template"] = template
        self.manager.save(record["topology"])
        with self.assertRaisesRegex(LabError, "配置目录属于其他设备定义"):
            self.manager.deploy(self.manager.read("native-lab"))

    def test_configuration_tree_refuses_symlink_and_hardlink(self):
        folder = self.directory / "config"
        folder.mkdir()
        target = self.directory / "outside"
        target.write_text("private")
        (folder / "linked").symlink_to(target)
        with self.assertRaises(LabError):
            configuration_files(folder)
        (folder / "linked").unlink()
        os.link(target, folder / "linked")
        with self.assertRaises(LabError):
            configuration_files(folder)

    def test_frr_profile_retains_daemon_checks_and_saved_config(self):
        record = self.lab(descriptor("frr"))
        cid = record["runtime"]["nodes"]["r1"]["id"]
        self.host.running_configs[cid] = "hostname R1\nrouter ospf\n ospf router-id 203.0.113.5\n"
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertTrue(result["ok"], result)
        self.assertIn("203.0.113.5", result["config"])
        self.host.live_daemons = "zebra"
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("协议进程", result["error"])

    def test_frr_save_honors_descriptor_output_check_before_success_metadata(self):
        definition = descriptor("frr")
        definition["actions"]["save_config"]["contains"] = ["THIS_EXPECTATION_DOES_NOT_MATCH"]
        self.lab(definition)
        result = self.manager.save_configs("native-lab", "r1")["results"][0]
        self.assertFalse(result["ok"])
        self.assertIn("保存输出", result["error"])
        self.assertIsNone(self.manager.configs("native-lab", "r1")["r1"]["saved_at"])

    def test_bootstrap_uses_exec_and_supervised_container_not_detached_exec(self):
        self.lab()
        creates = [argv for argv, _ in self.host.calls if argv[3:4] == ["create"]]
        self.assertTrue(all("--init" in argv and "--entrypoint" in argv for argv in creates))
        self.assertIn('exec "$@"', BOOTSTRAP)
        self.assertIn("/proc/$service_pid/cmdline", EXECUTED)
        self.assertFalse(any(argv[3:5] == ["exec", "-d"] for argv, _ in self.host.calls))


if __name__ == "__main__":
    unittest.main()
