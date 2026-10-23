"""Run with: python3 -m unittest discover -s tests -p 'test_lab.py' -v.

FakeHost models ownership, container restarts and namespace-local interfaces.
These tests do NOT replace the Linux/Docker integration procedure in the guide.
"""
import copy
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script" / "python"))
from lab_core import LABEL, LabError, LabManager, validate_topology
from lab_server import create_app, acquire_lock


def example():
    return json.loads((ROOT / "examples" / "basic-lab.json").read_text(encoding="utf-8"))


class FakeHost:
    def __init__(self):
        self.containers = {}
        self.calls = []
        self.interfaces = {}
        self.counter = 0
        self.ifindex = 10
        self.fail_link = False
        self.fail_remove = False
        self.missing_image = False
        self.running_configs = {}
        self.daemons = "bgpd=yes\nospfd=yes\nospf6d=yes\n"
        self.live_daemons = "zebra bgpd ospfd ospf6d staticd mgmtd"
        self.save_error = False

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        output = ""
        if argv[0] == "docker":
            args = argv[3:]
            if args[:2] == ["image", "inspect"]:
                if self.missing_image:
                    raise LabError("No such image")
                output = "[]"
            elif args[0] == "run":
                output = f"{os.getuid()}\n{os.getgid()}\n" + base64.b64encode(self.daemons.encode()).decode() + "\n\n\n"
            elif args[0] == "create":
                name = args[args.index("--name") + 1]
                if any(item["Name"] == "/" + name for item in self.containers.values()):
                    raise LabError("container name is already in use")
                self.counter += 1
                cid = "c{:063d}".format(self.counter)
                labels = dict(args[index + 1].split("=", 1) for index, value in enumerate(args) if value == "--label")
                self.containers[cid] = {"Id": cid, "Name": "/" + name, "Config": {"Labels": labels},
                                        "HostConfig": {"NetworkMode": "none"}, "State": {"Running": False, "Pid": 1000 + self.counter}}
                mounts = []
                for index, value in enumerate(args):
                    if value == "--mount":
                        fields = dict(pair.split("=", 1) for pair in args[index + 1].split(","))
                        mounts.append({"Type": fields["type"], "Source": fields["src"], "Destination": fields["dst"], "RW": True})
                self.containers[cid]["Mounts"] = mounts
                self.running_configs[cid] = "!\n"
                self.interfaces[cid] = {"lo": {"ifname": "lo", "ifindex": 1, "flags": ["UP"]}}
                output = cid
            elif args[0] == "start":
                self.containers[args[1]]["State"]["Running"] = True
            elif args[0] == "inspect":
                cid = args[-1]
                if cid not in self.containers:
                    raise LabError("No such container")
                output = json.dumps([self.containers[cid]])
            elif args[0] == "ps":
                filters = [args[index + 1][len("label="):].split("=", 1) for index, value in enumerate(args) if value == "--filter"]
                output = "\n".join(cid for cid, item in self.containers.items() if all(item["Config"]["Labels"].get(key) == value for key, value in filters))
            elif args[0] == "rm":
                if self.fail_remove:
                    raise LabError("simulated Docker remove failure")
                cid = args[-1]
                removed = set(row["ifindex"] for row in self.interfaces[cid].values() if row["ifname"] != "lo")
                del self.containers[cid]
                del self.interfaces[cid]
                for interfaces in self.interfaces.values():
                    for name in list(interfaces):
                        if interfaces[name].get("link_index") in removed:
                            del interfaces[name]
            elif args[0] == "exec":
                output = "command output"
                index = next((i for i, arg in enumerate(args) if arg in self.containers), None)
                if index is not None:
                    cid, command = args[index], args[index + 1:]
                    mounts = self.containers[cid].get("Mounts", [])
                    folder = Path(mounts[0]["Source"]) if mounts else None
                    if command == ["cat", "/etc/frr/daemons"]:
                        output = self.daemons
                    elif command == ["vtysh", "-c", "show daemons"]:
                        output = self.live_daemons
                    elif command[:2] == ["sh", "-c"] and "daemon_list" in command[-1]:
                        output = "mgmtd zebra staticd bgpd ospfd ospf6d"
                    elif command == ["vtysh", "-c", "show running-config"]:
                        output = self.running_configs[cid]
                    elif command == ["vtysh", "-b"] and folder:
                        self.running_configs[cid] = (folder / "frr.conf").read_text()
                    elif command == ["vtysh", "-w"]:
                        if self.save_error:
                            raise LabError("simulated save error")
                        if folder:
                            (folder / "frr.conf").write_text(self.running_configs[cid])
                        output = "Configuration saved"
                    elif command[:2] == ["sh", "-c"] and "config-read" in command:
                        output = {"frr.conf": self.running_configs[cid], "daemons": self.daemons,
                                  "vtysh.conf": "service integrated-vtysh-config\n"}[command[-1].split("/")[-1]]
            elif args[0] == "info":
                output = "linux"
            elif args[:2] == ["image", "ls"]:
                output = "alpine/vpcs:latest\nalpine/frr:latest"
            else:
                raise AssertionError("Unexpected Docker command: " + repr(args))
        elif argv[:3] == ["ip", "link", "add"]:
            if self.fail_link:
                self.fail_link = False
                raise LabError("simulated veth create failure")
            locations = [i for i, arg in enumerate(argv) if arg == "netns"]
            self.assert_namespace_pair(argv, locations)
            endpoints = [(self.cid_for_pid(argv[i + 1]), argv[i - 1]) for i in locations]
            indexes = [self.ifindex, self.ifindex + 1]
            self.ifindex += 2
            for index, (cid, name) in enumerate(endpoints):
                if name in self.interfaces[cid]:
                    raise LabError("interface already exists")
                self.interfaces[cid][name] = {"ifname": name, "ifindex": indexes[index], "link_index": indexes[1-index], "flags": [], "linkinfo": {"info_kind": "veth"}}
        elif argv[0] == "nsenter":
            cid = self.cid_for_pid(argv[2])
            args = argv[6:]
            if args == ["-j", "-d", "link", "show"]:
                output = json.dumps(list(self.interfaces[cid].values()))
            elif args[:3] == ["link", "add", "br0"]:
                self.ifindex += 1
                self.interfaces[cid]["br0"] = {"ifname": "br0", "ifindex": self.ifindex, "flags": [], "linkinfo": {"info_kind": "bridge"}}
            elif args[:2] == ["link", "set"]:
                name_index = 3 if args[2] == "dev" else 2
                interface = self.interfaces[cid][args[name_index]]
                if "alias" in args:
                    interface["ifalias"] = args[args.index("alias") + 1]
                if args[-1] == "up":
                    interface["flags"] = ["UP"]
                if "master" in args:
                    interface["master"] = args[-1]
            elif args[:2] in (["addr", "add"], ["addr", "replace"]) or args[0] in ("-4", "-6"):
                pass
            else:
                raise AssertionError("Unexpected namespace command: " + repr(args))
        else:
            raise AssertionError("Unexpected command: " + repr(argv))
        return subprocess.CompletedProcess(argv, 0, output, "")

    def cid_for_pid(self, pid):
        return next(cid for cid, item in self.containers.items() if item["State"]["Pid"] == int(pid))

    @staticmethod
    def assert_namespace_pair(argv, locations):
        if len(locations) != 2 or "veth" not in argv or argv[locations[0] + 1] == argv[locations[1] + 1]:
            raise AssertionError("Both ends must be created in distinct container namespaces")


class ValidationTests(unittest.TestCase):
    def test_example_and_empty_lab(self):
        self.assertEqual(len(validate_topology(example())["nodes"]), 5)
        self.assertEqual(validate_topology({"version": 1, "id": "empty", "name": "空实验", "nodes": [], "links": []})["nodes"], [])

    def test_path_traversal_and_shell_in_image(self):
        for key, value in (("id", "../other"), ("id", "--option")):
            lab = example(); lab[key] = value
            with self.assertRaises(LabError): validate_topology(lab)
        lab = example(); lab["nodes"][0]["image"] = "alpine; touch /tmp/pwn"
        with self.assertRaises(LabError): validate_topology(lab)

    def test_optional_canvas_dimensions(self):
        lab = example()
        self.assertNotIn("width", validate_topology(lab)["nodes"][0])
        self.assertNotIn("height", validate_topology(lab)["nodes"][0])
        for width, height in ((96, 72), (215.5, 136), (640, 640)):
            with self.subTest(width=width, height=height):
                lab["nodes"][0].update(width=width, height=height)
                node = validate_topology(lab)["nodes"][0]
                self.assertEqual((node["width"], node["height"]), (width, height))

    def test_invalid_canvas_dimensions(self):
        for key, minimum in (("width", 96), ("height", 72)):
            for value in (None, True, "150", float("nan"), float("inf"), -1, minimum - 1, 641):
                with self.subTest(key=key, value=value):
                    lab = example(); lab["nodes"][0][key] = value
                    with self.assertRaisesRegex(LabError, "尺寸"):
                        validate_topology(lab)

    def test_duplicate_or_missing_endpoint(self):
        lab = example(); lab["links"][1]["a"] = copy.deepcopy(lab["links"][0]["a"])
        with self.assertRaisesRegex(LabError, "一个端口"): validate_topology(lab)
        for value in ("absent", [], None):
            lab = example(); lab["links"][0]["a"]["node"] = value
            with self.assertRaises(LabError): validate_topology(lab)

    def test_invalid_ip_gateway_and_switch_l3(self):
        lab = example(); lab["nodes"][0]["ports"][0]["address"] = "10.10.1.1"
        with self.assertRaises(LabError): validate_topology(lab)
        lab = example(); lab["nodes"][-1]["gateway"] = "192.0.2.1"
        with self.assertRaisesRegex(LabError, "默认网关"): validate_topology(lab)
        lab = example(); lab["nodes"][1]["ports"][0]["address"] = "10.0.0.1/24"
        with self.assertRaisesRegex(LabError, "交换机"): validate_topology(lab)

    def test_invalid_interface_and_nonfinite_position(self):
        for name in ("lo", "br0", "long-interface-name", "eth0;id"):
            lab = example(); lab["nodes"][0]["ports"][0]["name"] = name
            with self.assertRaises(LabError): validate_topology(lab)
        lab = example(); lab["nodes"][0]["x"] = float("nan")
        with self.assertRaises(LabError): validate_topology(lab)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = FakeHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.record = self.manager.save(example())

    def tearDown(self):
        self.temp.cleanup()

    def test_deploy_bridge_address_gateway_and_cleanup(self):
        self.manager.deploy(self.record)
        self.assertEqual(self.manager.status("first-lab")["runtime"]["phase"], "running")
        self.assertEqual(len(self.host.containers), 5)
        pairs = [argv for argv, _ in self.host.calls if argv[:3] == ["ip", "link", "add"]]
        self.assertEqual(len(pairs), 4)
        self.assertTrue(any("master" in argv for argv, _ in self.host.calls))
        self.assertTrue(any("default" in argv for argv, _ in self.host.calls))
        self.manager.destroy(self.record)
        self.assertEqual(self.host.containers, {})
        self.assertEqual(self.manager.read("first-lab")["runtime"]["phase"], "idle")
        self.assertEqual(len(self.manager.read("first-lab")["topology"]["nodes"]), 5)

    def test_missing_image_or_unconnected_address_has_no_side_effects(self):
        self.host.missing_image = True
        with self.assertRaisesRegex(LabError, "镜像"): self.manager.deploy(self.record)
        self.assertFalse(self.host.containers)
        self.host.missing_image = False
        self.record["topology"]["links"] = []
        before = len(self.host.calls)
        with self.assertRaisesRegex(LabError, "网线"): self.manager.deploy(self.record)
        self.assertEqual(len(self.host.calls), before)

    def test_name_collision_preserves_existing_container(self):
        foreign = {"Id": "foreign", "Name": "/rov-first-lab-r1", "Config": {"Labels": {}}, "State": {"Pid": 9000}}
        self.host.containers["foreign"] = copy.deepcopy(foreign)
        with self.assertRaisesRegex(LabError, "already in use"):
            self.manager.deploy(self.record)
        self.assertEqual(self.host.containers, {"foreign": foreign})

    def test_link_failure_rolls_back_only_own_resources(self):
        foreign = {"Id": "foreign", "Name": "/production", "Config": {"Labels": {}}, "State": {"Pid": 9000}}
        self.host.containers["foreign"] = foreign
        self.host.fail_link = True
        with self.assertRaisesRegex(LabError, "已回滚"): self.manager.deploy(self.record)
        self.assertEqual(list(self.host.containers), ["foreign"])
        self.assertNotIn("deployment", self.manager.read("first-lab")["runtime"])

    def test_failed_rollback_keeps_recoverable_deployment(self):
        self.host.fail_link = self.host.fail_remove = True
        with self.assertRaisesRegex(LabError, "回滚未完成"): self.manager.deploy(self.record)
        saved = self.manager.read("first-lab")
        self.assertTrue(saved["runtime"]["deployment"])
        self.host.fail_remove = False
        self.manager.destroy(saved)
        self.assertFalse(self.host.containers)

    def test_changed_ownership_refuses_cleanup_and_preserves_record(self):
        self.manager.deploy(self.record)
        cid = next(iter(self.host.containers))
        self.host.containers[cid]["Config"]["Labels"][LABEL + ".deployment"] = "other"
        with self.assertRaisesRegex(LabError, "归属"): self.manager.destroy(self.record)
        self.assertEqual(len(self.host.containers), 5)
        self.assertTrue(self.manager.read("first-lab")["runtime"]["deployment"])

    def test_restart_and_missing_link_report_degraded(self):
        self.manager.deploy(self.record)
        cid = self.record["runtime"]["nodes"]["r1"]["id"]
        self.host.containers[cid]["State"]["Pid"] += 100
        self.assertEqual(self.manager.status("first-lab")["runtime"]["phase"], "degraded")
        self.host.containers[cid]["State"]["Pid"] -= 100
        self.host.interfaces[cid]["eth0"]["flags"] = []
        self.assertEqual(self.manager.status("first-lab")["runtime"]["phase"], "degraded")

    def test_edit_and_delete_blocked_until_cleanup(self):
        self.manager.deploy(self.record)
        with self.assertRaises(LabError): self.manager.save(example())
        with self.assertRaises(LabError): self.manager.delete("first-lab")
        self.manager.destroy(self.record)
        self.manager.save(example())
        self.manager.delete("first-lab")
        self.assertEqual(self.manager.list_labs(), [])

    def test_create_crash_recovered_by_labels_without_recorded_id(self):
        self.manager.deploy(self.record)
        self.record["runtime"]["nodes"] = {}
        self.manager.write(self.record)
        self.manager.destroy(self.record)
        self.assertFalse(self.host.containers)

    def test_single_command_never_uses_a_host_shell(self):
        self.manager.deploy(self.record)
        self.manager.command("first-lab", "r1", "printf '%s' 'hello; touch /tmp/host'")
        argv, kwargs = self.host.calls[-1]
        self.assertIn("exec", argv)
        self.assertEqual(argv[-3:], ["printf", "%s", "hello; touch /tmp/host"])
        self.assertNotIn("shell", kwargs)

    def test_interrupted_state_and_preview_refuse_deployment(self):
        self.record["runtime"]["phase"] = "deploying"
        self.manager.write(self.record)
        self.assertEqual(self.manager.status("first-lab")["runtime"]["phase"], "error")
        preview = LabManager(self.temp.name, runner=self.host, preview=True)
        with self.assertRaisesRegex(LabError, "设计模式"): preview.start_job("first-lab", "deploy")
        self.assertFalse(self.host.calls)

    def test_concurrent_jobs_and_edits_are_rejected(self):
        entered, release = threading.Event(), threading.Event()
        original = self.manager.deploy
        def paused_deploy(record):
            entered.set()
            release.wait(5)
            original(record)
        self.manager.deploy = paused_deploy
        response = self.manager.start_job("first-lab", "deploy")
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(response["runtime"]["phase"], "deploying")
            with self.assertRaisesRegex(LabError, "正在执行"):
                self.manager.start_job("first-lab", "destroy")
            with self.assertRaises(LabError):
                self.manager.save(example())
        finally:
            release.set()
            for thread in threading.enumerate():
                if thread.name == "lab-job-first-lab":
                    thread.join(5)
        self.assertIsNone(self.manager.busy)
        self.assertEqual(response["runtime"]["phase"], "deploying", "response must not share mutable job state")
        self.assertEqual(self.manager.read("first-lab")["runtime"]["phase"], "running")

    def test_failed_job_persists_error_for_ui(self):
        self.host.missing_image = True
        self.manager._job(self.record, "deploy")
        record = self.manager.read("first-lab")
        self.assertEqual(record["runtime"]["phase"], "error")
        self.assertIn("镜像", record["runtime"]["error"])
        self.assertFalse(self.manager.busy)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = LabManager(self.temp.name, preview=True)
        self.web = Path(self.temp.name) / "dist"
        (self.web / "assets").mkdir(parents=True)
        (self.web / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
        (self.web / "assets" / "app-test.js").write_text('console.log("built")', encoding="utf-8")
        (Path(self.temp.name) / "private.js").write_text("not public", encoding="utf-8")
        self.client = TestClient(create_app(self.manager, "test-token", self.web))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, auth=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if auth: headers["Authorization"] = "Bearer test-token"
        if origin: headers["Origin"] = origin
        response = self.client.request(method, path, headers=headers, json=data)
        return response.status_code, response.content

    def test_auth_origin_and_static_routes(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/api/bootstrap", auth=False)[0], 401)
        self.assertEqual(self.request("/api/labs/first-lab", "PUT", example(), origin="http://untrusted.invalid")[0], 403)
        self.assertEqual(self.request("/../script/python/lab_core.py")[0], 404)
        self.assertFalse(self.manager.list_labs())

    def test_save_reload_and_preview_deploy_error(self):
        lab = example()
        lab["nodes"][0].update(width=240, height=180, x=315, y=207)
        self.assertEqual(self.request("/api/labs/first-lab", "PUT", lab)[0], 200)
        code, body = self.request("/api/labs/first-lab")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)["topology"]["links"]), 4)
        node = json.loads(body)["topology"]["nodes"][0]
        self.assertEqual((node["width"], node["height"], node["x"], node["y"]), (240, 180, 315, 207))
        stored = self.manager.read("first-lab")["topology"]["nodes"][0]
        self.assertEqual(stored, node)
        code, _ = self.request("/api/labs/first-lab/deploy", "POST", {})
        self.assertEqual(code, 400)
        self.assertEqual(self.request("/api/labs/first-lab", "DELETE")[0], 200)

    def test_vite_assets_are_served_without_exposing_source(self):
        self.assertEqual(self.request("/assets/app-test.js", auth=False), (200, b'console.log("built")'))
        response = self.client.get("/assets/app-test.js")
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/javascript")
        for path in ("/src/main.ts", "/package.json", "/assets/missing.js", "/assets/%2e%2e/%2e%2e/private.js", "/assets/%2e%2e%5c%2e%2e%5cprivate.js"):
            self.assertEqual(self.request(path)[0], 404, path)

    def test_missing_build_explains_build_step_and_keeps_api_available(self):
        (self.web / "index.html").unlink()
        code, body = self.request("/")
        self.assertEqual(code, 503)
        self.assertIn(b"npm --prefix web run build", body)
        self.assertEqual(self.request("/api/bootstrap")[0], 200)

    def test_second_server_directory_lock(self):
        lock = acquire_lock(Path(self.temp.name))
        try:
            with self.assertRaises(LabError): acquire_lock(Path(self.temp.name))
        finally:
            lock.close()


if __name__ == "__main__":
    unittest.main()
