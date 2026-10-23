"""Docker-only topology deployment. All links stay inside owned namespaces.

No third-party Python packages are needed. The executor is injectable so that
validation, rollback and ownership checks can be tested without a Docker host.
"""
import copy
import datetime
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid


LABEL = "io.route-ovs.lab"
CATALOG = [
    {"kind": "router", "title": "FRR 路由器", "image": "alpine/frr:latest", "ports": 4, "prefix": "R"},
    {"kind": "switch", "title": "以太网交换机", "image": "alpine/vpcs:latest", "ports": 8, "prefix": "SW"},
    {"kind": "host", "title": "VPCS 终端", "image": "alpine/vpcs:latest", "ports": 1, "prefix": "PC"},
]
FRR_START = "sed -i 's/^bgpd=no/bgpd=yes/;s/^ospfd=no/ospfd=yes/;s/^ospf6d=no/ospf6d=yes/' /etc/frr/daemons && exec /usr/lib/frr/docker-start"


class LabError(Exception):
    pass


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value):
        raise LabError("ID 必须是 1–32 位小写字母、数字、下划线或短横线")
    return value


def string(value, label, maximum=128, empty=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise LabError(label + "格式错误或过长")
    value = value.strip()
    if not empty and not value:
        raise LabError(label + "不能为空")
    return value


def validate_topology(raw):
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise LabError("拓扑文件需要 version: 1")
    result = {"version": 1, "id": identifier(raw.get("id")),
              "name": string(raw.get("name"), "实验名称", 80), "nodes": [], "links": []}
    nodes, links = raw.get("nodes"), raw.get("links")
    if not isinstance(nodes, list) or len(nodes) > 64 or not isinstance(links, list) or len(links) > 256:
        raise LabError("拓扑最多包含 64 台设备和 256 条链路")
    by_id, names = {}, set()
    for raw_node in nodes:
        if not isinstance(raw_node, dict):
            raise LabError("设备必须是 JSON 对象")
        nid = identifier(raw_node.get("id"))
        name = string(raw_node.get("name"), "设备名称", 32)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise LabError("设备名称仅支持字母、数字、点、下划线和短横线")
        if nid in by_id or name in names:
            raise LabError("设备 ID 或名称重复: " + name)
        kind = raw_node.get("kind")
        if kind not in ("router", "switch", "host"):
            raise LabError("未知设备类型")
        image = string(raw_node.get("image"), "镜像", 255)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]*", image):
            raise LabError("镜像名称不合法")
        node = {"id": nid, "name": name, "kind": kind, "image": image, "ports": []}
        for axis in ("x", "y"):
            value = raw_node.get(axis, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 100000:
                raise LabError("设备坐标无效")
            node[axis] = value
        # Optional canvas metadata; version 1 files without sizes keep their defaults.
        for dimension, minimum in (("width", 96), ("height", 72)):
            if dimension not in raw_node:
                continue
            value = raw_node[dimension]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= 640:
                raise LabError(f"设备尺寸无效：{dimension} 必须为 {minimum}–640")
            node[dimension] = value
        ports = raw_node.get("ports")
        if not isinstance(ports, list) or not 1 <= len(ports) <= 32:
            raise LabError("每台设备需有 1–32 个端口")
        port_names, addresses = set(), []
        for port in ports:
            if not isinstance(port, dict):
                raise LabError("端口格式错误")
            pname = port.get("name")
            if not isinstance(pname, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", pname) or pname in ("lo", "br0") or pname in port_names:
                raise LabError("接口名无效或重复（最多 15 字符，不使用 lo/br0）")
            address = string(port.get("address", ""), "端口地址", 64, empty=True)
            if address:
                try:
                    if "/" not in address:
                        raise ValueError()
                    parsed = ipaddress.ip_interface(address)
                except ValueError:
                    raise LabError("地址需要 CIDR 格式，例如 10.0.0.1/24")
                if kind == "switch":
                    raise LabError("二层交换机端口不配置 IP 地址")
                addresses.append(parsed)
                address = str(parsed)
            node["ports"].append({"name": pname, "address": address})
            port_names.add(pname)
        gateway = string(raw_node.get("gateway", ""), "默认网关", 64, empty=True)
        if gateway:
            try:
                parsed_gateway = ipaddress.ip_address(gateway)
            except ValueError:
                raise LabError("默认网关必须是 IP 地址")
            if kind == "switch" or not any(parsed_gateway.version == addr.version and parsed_gateway in addr.network and parsed_gateway != addr.ip for addr in addresses):
                raise LabError("默认网关必须位于本设备的某个端口子网内，且不能是本机地址")
        node["gateway"] = gateway
        command = raw_node.get("command", [])
        if not isinstance(command, list) or len(command) > 64 or any(not isinstance(arg, str) or not arg or len(arg) > 4096 or "\x00" in arg for arg in command):
            raise LabError("启动命令必须是字符串数组")
        node["command"] = command
        config = string(raw_node.get("config", ""), "FRR 配置", 32768, empty=True)
        if config and kind != "router":
            raise LabError("只有 FRR 路由器支持启动配置")
        node["config"] = config
        by_id[nid] = node
        names.add(name)
        result["nodes"].append(node)
    used, link_ids = set(), set()
    for raw_link in links:
        if not isinstance(raw_link, dict):
            raise LabError("链路格式错误")
        lid = identifier(raw_link.get("id"))
        if lid in link_ids:
            raise LabError("链路 ID 重复")
        link_ids.add(lid)
        link = {"id": lid}
        for side in ("a", "b"):
            end = raw_link.get(side)
            if not isinstance(end, dict) or not isinstance(end.get("node"), str) or end.get("node") not in by_id:
                raise LabError("链路引用了不存在的设备")
            node_id, port_name = end["node"], end.get("port")
            if not isinstance(port_name, str) or port_name not in {p["name"] for p in by_id[node_id]["ports"]}:
                raise LabError("链路引用了不存在的端口")
            pair = (node_id, port_name)
            if pair in used:
                raise LabError("一个端口只能连接一根网线: " + ".".join(pair))
            used.add(pair)
            link[side] = {"node": node_id, "port": port_name}
        if link["a"]["node"] == link["b"]["node"]:
            raise LabError("第一版不支持设备自身环回连线")
        result["links"].append(link)
    return result


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".write-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def execute(argv, timeout=30, input_text=None, check=True):
    try:
        result = subprocess.run(argv, input=input_text, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LabError("命令执行失败 {}: {}".format(argv[0], exc)) from exc
    if check and result.returncode:
        raise LabError((result.stderr.strip() or result.stdout.strip() or "命令失败")[-6000:])
    return result


class LabManager:
    def __init__(self, directory, runner=execute, preview=False, docker_socket="/var/run/docker.sock"):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.preview = preview
        self.docker = ["docker", "--host", "unix://" + docker_socket]
        self.lock = threading.RLock()
        self.busy = None

    def path(self, lab_id):
        return self.directory / (identifier(lab_id) + ".json")

    def read(self, lab_id):
        try:
            value = json.loads(self.path(lab_id).read_text(encoding="utf-8"))
            validate_topology(value["topology"])
            return value
        except FileNotFoundError:
            raise LabError("实验不存在")
        except (ValueError, KeyError, TypeError):
            raise LabError("实验记录损坏，请保留文件并检查")

    def write(self, record):
        with self.lock:
            record["updated_at"] = stamp()
            atomic_json(self.path(record["topology"]["id"]), record)

    def save(self, topology):
        topology = validate_topology(topology)
        with self.lock:
            if self.path(topology["id"]).exists():
                record = self.read(topology["id"])
                if self.busy == topology["id"] or record["runtime"].get("deployment"):
                    raise LabError("设备已经部署或正在操作，请先清理设备再修改拓扑")
                record["topology"] = topology
            else:
                record = {"topology": topology, "runtime": {"phase": "idle", "nodes": {}, "logs": []}}
            self.write(record)
            return record

    def list_labs(self):
        result = []
        with self.lock:
            for path in sorted(self.directory.glob("*.json")):
                record = self.read(path.stem)
                result.append({"id": path.stem, "name": record["topology"]["name"],
                               "nodes": len(record["topology"]["nodes"]), "phase": record["runtime"]["phase"]})
        return result

    def delete(self, lab_id):
        with self.lock:
            record = self.read(lab_id)
            if self.busy == lab_id or record["runtime"].get("deployment"):
                raise LabError("请先清理设备，再删除实验文件")
            self.path(lab_id).unlink()

    def run(self, *argv, **kwargs):
        return self.runner(list(argv), **kwargs).stdout.strip()

    def dock(self, *argv, **kwargs):
        return self.run(*(self.docker + list(argv)), **kwargs)

    def environment(self):
        errors = []
        if self.preview:
            errors.append("设计模式：可以编辑和保存拓扑，不会创建容器")
        if sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            errors.append("真实部署需要在 Linux Docker 宿主机以 root 运行后端")
        for tool in ("docker", "ip", "nsenter"):
            if not shutil.which(tool):
                errors.append("缺少宿主机命令: " + tool)
        images = []
        if not errors:
            try:
                if self.dock("info", "--format", "{{.OSType}}", timeout=5) != "linux":
                    raise LabError("需要运行 Linux 容器的本机 Docker daemon")
                images = sorted(set(line for line in self.dock("image", "ls", "--format", "{{.Repository}}:{{.Tag}}", timeout=5).splitlines() if "<none>" not in line))
            except LabError as exc:
                errors.append(str(exc))
        return {"ready": not errors, "preview": self.preview, "errors": errors, "images": images}

    def authorize(self):
        environment = self.environment()
        if not environment["ready"]:
            raise LabError("；".join(environment["errors"]))

    def note(self, record, message):
        record["runtime"].setdefault("logs", []).append({"time": stamp(), "message": message})
        record["runtime"]["logs"] = record["runtime"]["logs"][-200:]
        self.write(record)

    def inspect(self, cid):
        try:
            return json.loads(self.dock("inspect", "--type", "container", cid))[0]
        except (ValueError, IndexError):
            raise LabError("Docker inspect 返回无效数据")

    def owned(self, record, item):
        labels = item.get("Config", {}).get("Labels") or {}
        runtime = record["runtime"]
        if (labels.get(LABEL) != record["topology"]["id"] or
                labels.get(LABEL + ".deployment") != runtime.get("deployment")):
            raise LabError("容器归属不匹配，拒绝操作: " + item.get("Name", item.get("Id", "")))
        return item

    def live(self, record, node_id):
        saved = record["runtime"]["nodes"][node_id]
        item = self.owned(record, self.inspect(saved["id"]))
        state = item["State"]
        if not state.get("Running") or state.get("Paused") or state.get("Restarting") or state.get("Pid", 0) <= 0:
            raise LabError("设备未正常运行: " + saved["name"])
        if item.get("HostConfig", {}).get("NetworkMode") != "none":
            raise LabError("设备网络模式已改变，拒绝修改命名空间")
        if saved.get("pid") and saved["pid"] != state["Pid"]:
            raise LabError("设备已在外部重启，veth 可能丢失，请清理后重新部署")
        return item

    def ns(self, record, node_id, *argv):
        item = self.live(record, node_id)
        return self.run("nsenter", "-t", str(item["State"]["Pid"]), "-n", "--", *argv)

    def start_job(self, lab_id, action):
        if action not in ("deploy", "destroy"):
            raise LabError("未知操作")
        self.authorize()
        with self.lock:
            if self.busy is not None:
                raise LabError("另一个部署或清理任务正在执行，请稍后重试")
            record = self.read(lab_id)
            if action == "deploy" and record["runtime"].get("deployment"):
                raise LabError("实验仍有部署记录，请先清理设备")
            self.busy = lab_id
            record["runtime"]["phase"] = "deploying" if action == "deploy" else "destroying"
            record["runtime"]["error"] = ""
            self.write(record)
            response = copy.deepcopy(record)
            threading.Thread(target=self._job, args=(record, action), name="lab-job-" + lab_id, daemon=False).start()
        return response

    def _job(self, record, action):
        try:
            if action == "deploy":
                self.deploy(record)
            else:
                self.destroy(record)
        except Exception as exc:
            record["runtime"]["phase"] = "error"
            record["runtime"]["error"] = str(exc)
            self.note(record, "操作失败: " + str(exc))
        finally:
            with self.lock:
                self.busy = None

    def deploy(self, record):
        topology = validate_topology(record["topology"])
        if not topology["nodes"]:
            raise LabError("请先添加至少一台设备")
        connected = {(link[side]["node"], link[side]["port"]) for link in topology["links"] for side in ("a", "b")}
        for node in topology["nodes"]:
            for port in node["ports"]:
                if port["address"] and (node["id"], port["name"]) not in connected:
                    raise LabError(node["name"] + "." + port["name"] + " 配置了地址但尚未连接网线")
        # Check every image before creating any resource. Never silently pull.
        for image in sorted({node["image"] for node in topology["nodes"]}):
            try:
                self.dock("image", "inspect", image)
            except LabError:
                raise LabError("本机没有可用镜像 {}，请先 docker load / docker pull".format(image))
        runtime = record["runtime"]
        runtime.update(deployment=uuid.uuid4().hex, nodes={}, phase="deploying", error="", logs=[])
        self.note(record, "开始部署：所有设备使用独立网络命名空间，网线使用 veth")
        try:
            for node in topology["nodes"]:
                name = "rov-{}-{}".format(topology["id"], node["id"])
                args = ["create", "--name", name, "--hostname", node["name"], "--network", "none",
                        "--label", LABEL + "=" + topology["id"],
                        "--label", LABEL + ".deployment=" + runtime["deployment"],
                        "--label", LABEL + ".node=" + node["id"],
                        "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW"]
                if node["kind"] == "router":
                    args += ["--cap-add", "SYS_ADMIN", "--sysctl", "net.ipv4.ip_forward=1",
                             "--sysctl", "net.ipv6.conf.all.forwarding=1"]
                command = node["command"] or (["/bin/sh", "-c", FRR_START] if node["kind"] == "router" else ["sleep", "infinity"])
                cid = self.dock(*(args + [node["image"]] + command))
                runtime["nodes"][node["id"]] = {"id": cid, "name": name, "pid": 0}
                self.note(record, "创建设备 " + node["name"])
                self.dock("start", cid)
                item = self.live(record, node["id"])
                runtime["nodes"][node["id"]]["pid"] = item["State"]["Pid"]
                self.write(record)
                self.ns(record, node["id"], "ip", "link", "set", "lo", "up")
                if node["kind"] == "switch":
                    self.ns(record, node["id"], "ip", "link", "add", "br0", "type", "bridge", "stp_state", "1", "forward_delay", "2")
                    self.ns(record, node["id"], "ip", "link", "set", "br0", "up")
            for link in topology["links"]:
                a, b = link["a"], link["b"]
                ca, cb = self.live(record, a["node"]), self.live(record, b["node"])
                # Both endpoints are created directly inside the owned namespaces.
                # Removing the owned containers also removes partially created links.
                self.run("ip", "link", "add", "name", a["port"], "netns", str(ca["State"]["Pid"]),
                         "type", "veth", "peer", "name", b["port"], "netns", str(cb["State"]["Pid"]))
                for side in ("a", "b"):
                    end = link[side]
                    self.ns(record, end["node"], "ip", "link", "set", "dev", end["port"],
                            "alias", "route-ovs:" + runtime["deployment"] + ":" + link["id"] + ":" + side)
                    self.ns(record, end["node"], "ip", "link", "set", "dev", end["port"], "up")
                self.note(record, "连接 {}.{} ↔ {}.{}".format(a["node"], a["port"], b["node"], b["port"]))
            for node in topology["nodes"]:
                for port in node["ports"]:
                    if (node["id"], port["name"]) not in connected:
                        continue
                    if node["kind"] == "switch":
                        self.ns(record, node["id"], "ip", "link", "set", "dev", port["name"], "master", "br0")
                    elif port["address"]:
                        self.ns(record, node["id"], "ip", "addr", "add", port["address"], "dev", port["name"])
                if node["gateway"]:
                    family = "-6" if ":" in node["gateway"] else "-4"
                    self.ns(record, node["id"], "ip", family, "route", "add", "default", "via", node["gateway"])
                if node["config"]:
                    cid = runtime["nodes"][node["id"]]["id"]
                    for attempt in range(20):
                        try:
                            self.dock("exec", cid, "vtysh", "-c", "show version")
                            break
                        except LabError:
                            if attempt == 19:
                                raise
                            time.sleep(0.5)
                    self.dock("exec", "-i", "-u", "0", cid, "sh", "-c", "cat > /tmp/route-ovs-startup.conf", input_text=node["config"] + "\n")
                    self.dock("exec", "-u", "0", cid, "vtysh", "-f", "/tmp/route-ovs-startup.conf")
            for node in topology["nodes"]:
                self.live(record, node["id"])
            runtime["phase"] = "running"
            self.note(record, "部署完成。交换机 STP 收敛可能需要数秒。")
        except Exception as exc:
            self.note(record, "部署失败，正在回滚本次实验的设备: " + str(exc))
            try:
                self.destroy(record)
            except Exception as cleanup:
                raise LabError("{}；回滚未完成，请再次清理设备: {}".format(exc, cleanup)) from exc
            raise LabError("{}；本次设备已回滚".format(exc)) from exc

    def destroy(self, record):
        runtime = record["runtime"]
        if runtime.get("deployment"):
            # Labels recover even a create whose result wasn't saved before a crash.
            ids = self.dock("ps", "-aq", "--no-trunc", "--filter", "label=" + LABEL + "=" + record["topology"]["id"],
                            "--filter", "label=" + LABEL + ".deployment=" + runtime["deployment"]).splitlines()
            inventory = set(self.dock("ps", "-aq", "--no-trunc").splitlines())
            # A tracked ID that still exists must retain our labels. Never erase
            # its record merely because it disappeared from a filtered listing.
            for saved in runtime.get("nodes", {}).values():
                if saved["id"] in inventory:
                    self.owned(record, self.inspect(saved["id"]))
            items = [self.owned(record, self.inspect(cid)) for cid in ids]
            for item in items:
                self.dock("rm", "-f", "-v", item["Id"])
                self.note(record, "已清理 " + item.get("Name", item["Id"]).lstrip("/"))
        runtime.pop("deployment", None)
        runtime.update(nodes={}, phase="idle", error="")
        self.note(record, "设备和 veth 已清理，拓扑文件保留")

    def status(self, lab_id):
        with self.lock:
            record = self.read(lab_id)
            record["busy"] = self.busy == lab_id
        runtime = record["runtime"]
        if runtime["phase"] in ("deploying", "destroying") and not record["busy"]:
            runtime.update(phase="error", error="上次操作被中断，请清理设备后重新部署")
        if runtime["phase"] == "running" and not record["busy"]:
            try:
                live_links = {}
                for node in record["topology"]["nodes"]:
                    item = self.live(record, node["id"])
                    live_links[node["id"]] = {row["ifname"]: row for row in json.loads(self.run("nsenter", "-t", str(item["State"]["Pid"]), "-n", "--", "ip", "-j", "-d", "link", "show"))}
                for link in record["topology"]["links"]:
                    ends = []
                    for side in ("a", "b"):
                        end = link[side]
                        actual = live_links[end["node"]].get(end["port"], {})
                        alias = "route-ovs:" + runtime["deployment"] + ":" + link["id"] + ":" + side
                        if actual.get("ifalias") != alias or "UP" not in actual.get("flags", []):
                            raise LabError("链路缺失或关闭: " + end["node"] + "." + end["port"])
                        ends.append(actual)
                    if ends[0].get("link_index") != ends[1].get("ifindex") or ends[1].get("link_index") != ends[0].get("ifindex"):
                        raise LabError("veth 对端不匹配: " + link["id"])
            except (LabError, ValueError, KeyError) as exc:
                runtime.update(phase="degraded", error=str(exc))
        return record

    def command(self, lab_id, node_id, command):
        self.authorize()
        identifier(node_id)
        command = string(command, "命令", 4096)
        try:
            argv = shlex.split(command)
        except ValueError:
            raise LabError("命令引号不匹配")
        if not argv:
            raise LabError("命令不能为空")
        with self.lock:
            if self.busy is not None:
                raise LabError("部署或清理任务进行中")
            record = self.read(lab_id)
            if node_id not in record["runtime"].get("nodes", {}):
                raise LabError("设备尚未部署")
            item = self.live(record, node_id)
            result = self.runner(self.docker + ["exec", "-u", "0", item["Id"]] + argv, timeout=15, check=False)
        return {"code": result.returncode, "output": (result.stdout + result.stderr)[-65536:]}

    def terminal_target(self, lab_id, node_id, mode="default", expected=None):
        """Resolve a terminal to an owned, live container, never a client-supplied ID."""
        identifier(node_id)
        if mode not in ("default", "shell"):
            raise LabError("未知终端类型")
        with self.lock:
            record = self.read(lab_id)
            if self.busy == lab_id or record["runtime"]["phase"] in ("deploying", "destroying"):
                raise LabError("设备正在部署或清理，请稍后连接")
            if node_id not in record["runtime"].get("nodes", {}):
                raise LabError("设备尚未部署")
            item = self.live(record, node_id)
            node = next(n for n in record["topology"]["nodes"] if n["id"] == node_id)
            target = {"lab": lab_id, "node": node_id, "mode": mode,
                      "deployment": record["runtime"].get("deployment"), "container": item["Id"],
                      "program": "vtysh" if node["kind"] == "router" and mode == "default" else "sh"}
            if expected is not None and target != expected:
                raise LabError("设备部署已变化，请重新连接终端")
            return target
