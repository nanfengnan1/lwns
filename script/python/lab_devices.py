"""Built-in Docker device templates and lifecycle adapters.

Templates describe capabilities; adapters implement device-specific operations.
All host paths come from the server's data directory, never from topology input.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid


class LabError(Exception):
    pass


CATALOG = [
    {"id": "frr", "version": 1, "adapter": "frr", "kind": "router", "title": "FRR 路由器",
     "image": "alpine/frr:latest", "ports": 4, "prefix": "R", "console": "vtysh", "console_command": ["vtysh"],
     "capabilities": {"save_config": True, "startup_config": True}},
    {"id": "linux-bridge", "version": 1, "adapter": "linux-bridge", "kind": "switch", "title": "以太网交换机",
     "image": "alpine/vpcs:latest", "ports": 8, "prefix": "SW", "console": "sh", "console_command": ["sh", "-i"],
     "capabilities": {"save_config": False, "startup_config": False}},
    {"id": "linux-host", "version": 1, "adapter": "linux", "kind": "host", "title": "VPCS 终端",
     "image": "alpine/vpcs:latest", "ports": 1, "prefix": "PC", "console": "sh", "console_command": ["sh", "-i"],
     "capabilities": {"save_config": False, "startup_config": False}},
]
DEFAULT_TEMPLATES = {item["kind"]: item["id"] for item in CATALOG}


def template_for(node):
    template_id = node.get("template", DEFAULT_TEMPLATES.get(node["kind"]))
    template = next((item for item in CATALOG if item["id"] == template_id), None)
    if template is None or template["kind"] != node["kind"]:
        raise LabError("设备模板不存在或与设备类型不匹配")
    return template


def device_root(manager, lab_id, node_id=None):
    parts = ["devices", lab_id] + ([node_id] if node_id is not None else [])
    path = manager.directory
    for part in parts:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", part):
            raise LabError("配置目录标识无效")
        path = path / part
        if path.is_symlink():
            raise LabError("设备配置目录不能是符号链接")
    if not path.resolve().is_relative_to(manager.directory):
        raise LabError("设备配置目录越界")
    return path


def checked_file(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise LabError("设备配置必须是普通文件: " + path.name)
    return path


def text_file(path, maximum=32768):
    checked_file(path)
    if not path.exists():
        return ""
    if path.stat().st_size > maximum * 4:
        raise LabError("设备配置文件过大")
    value = path.read_text(encoding="utf-8")
    if len(value) > maximum or "\0" in value:
        raise LabError("设备配置文件无效或超过 32 KiB 字符")
    return value


def replace_text(path, content, uid=None, gid=None):
    checked_file(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if uid is not None:
            os.chown(temporary, uid, gid)
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def seed_hash(node):
    return hashlib.sha256(node.get("config", "").strip().encode()).hexdigest()


class DeviceAdapter:
    def prepare(self, manager, record, node):
        return []

    def command(self, node):
        return node["command"] or ["sleep", "infinity"]

    def started(self, manager, record, node):
        pass

    def linked(self, manager, record, node):
        pass

    def config_status(self, manager, record, node):
        return {"supported": False}

    def save_config(self, manager, record, node):
        raise LabError("该设备模板暂不支持保存运行配置")


class BridgeAdapter(DeviceAdapter):
    def started(self, manager, record, node):
        manager.ns(record, node["id"], "ip", "link", "add", "br0", "type", "bridge", "stp_state", "1", "forward_delay", "2")
        manager.ns(record, node["id"], "ip", "link", "set", "br0", "up")


class FrrAdapter(DeviceAdapter):
    files = ("daemons", "frr.conf", "vtysh.conf")
    daemon_list_script = ". /usr/lib/frr/frrcommon.sh && { daemon_list; printf '\\n'; }"
    # Read image defaults without starting routing daemons or touching host networking.
    defaults_script = """set -eu
id -u frr
id -g frr
for f in daemons frr.conf vtysh.conf; do
  if [ -f /etc/frr/$f ]; then base64 /etc/frr/$f | tr -d '\\n'; fi
  printf '\\n'
done
"""

    def paths(self, manager, record, node):
        root = device_root(manager, record["topology"]["id"], node["id"])
        directory = root / "frr"
        if directory.is_symlink():
            raise LabError("FRR 配置目录不能是符号链接")
        for name in self.files:
            checked_file(directory / name)
        return root, directory

    def metadata(self, root):
        value = text_file(root / "config-meta.json")
        return json.loads(value) if value else {}

    def write_metadata(self, root, metadata):
        replace_text(root / "config-meta.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    def backup(self, root, directory):
        backups = root / "backups"
        if backups.is_symlink():
            raise LabError("配置备份目录不能是符号链接")
        target = backups / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        target.mkdir(parents=True)
        for name in self.files:
            source = checked_file(directory / name)
            if source.exists():
                shutil.copy2(source, target / name)
        return target

    def prepare(self, manager, record, node):
        root, directory = self.paths(manager, record, node)
        metadata = self.metadata(root)
        rows = manager.dock("run", "--rm", "--pull", "never", "--network", "none", "--entrypoint", "sh", node["image"],
                            "-c", self.defaults_script).splitlines()
        try:
            uid, gid = int(rows[0]), int(rows[1])
            defaults = [base64.b64decode(value, validate=True).decode("utf-8") for value in (rows[2:] + [""] * 3)[:3]]
            if uid < 0 or gid < 0 or not defaults[0]:
                raise ValueError()
        except (ValueError, IndexError, UnicodeError) as exc:
            raise LabError("镜像缺少有效的 FRR 用户或 /etc/frr/daemons") from exc
        if not metadata:
            if directory.exists() and any(directory.iterdir()):
                raise LabError("FRR 配置目录初始化不完整，请保留文件并检查: " + str(directory))
            directory.mkdir(parents=True, exist_ok=True)
            os.chown(directory, uid, gid)
            os.chmod(directory, 0o750)
            daemons = re.sub(r"^(bgpd|ospfd|ospf6d)=no$", r"\1=yes", defaults[0], flags=re.M)
            vtysh = re.sub(r"^(?:no )?service integrated-vtysh-config\s*$", "", defaults[2], flags=re.M)
            content = (daemons, node["config"] or defaults[1] or "!\n", vtysh.rstrip() + "\nservice integrated-vtysh-config\n")
            for name, value in zip(self.files, content):
                replace_text(directory / name, value.rstrip() + "\n", uid, gid)
            metadata = {"template": "frr", "version": 1, "uid": uid, "gid": gid, "seed_hash": seed_hash(node), "saved_at": None}
            self.write_metadata(root, metadata)
        elif metadata.get("template") != "frr":
            raise LabError("设备持久化配置与模板不匹配")
        elif metadata.get("seed_hash") != seed_hash(node):
            # Only an explicit change to the topology's startup text replaces it.
            # CLI 'write memory' changes the shared file, but not this seed hash.
            self.backup(root, directory)
            replace_text(directory / "frr.conf", node["config"].rstrip() + "\n", metadata["uid"], metadata["gid"])
            metadata.update(seed_hash=seed_hash(node), saved_at=None)
            self.write_metadata(root, metadata)
        for name in self.files:
            if not (directory / name).is_file():
                raise LabError("FRR 持久化配置文件缺失: " + name)
            os.chown(directory / name, uid, gid)
            os.chmod(directory / name, 0o640)
        os.chown(directory, uid, gid)
        os.chmod(directory, 0o750)
        if (metadata["uid"], metadata["gid"]) != (uid, gid):
            metadata.update(uid=uid, gid=gid)
            self.write_metadata(root, metadata)
        if "," in str(directory):
            raise LabError("Docker 共享配置目录路径不能含逗号")
        return ["--cap-add", "SYS_ADMIN", "--sysctl", "net.ipv4.ip_forward=1", "--sysctl", "net.ipv6.conf.all.forwarding=1",
                "--mount", "type=bind,src=" + str(directory) + ",dst=/etc/frr"]

    def command(self, node):
        return node["command"] or ["/usr/lib/frr/docker-start"]

    def ready(self, manager, record, node):
        item = manager.live(record, node["id"])
        expected = self.required_daemons(manager, item)
        for attempt in range(20):
            try:
                self.check_daemons(manager, item, expected)
                return item
            except LabError:
                if attempt == 19:
                    raise
                time.sleep(0.5)

    def required_daemons(self, manager, item):
        # The image's own startup list includes always-on services (staticd,
        # mgmtd) which are not represented by '=yes' in /etc/frr/daemons.
        expected = set(manager.dock("exec", item["Id"], "sh", "-c", self.daemon_list_script).split())
        if not expected or any(not re.fullmatch(r"[a-z][a-z0-9]*", name) for name in expected):
            raise LabError("无法确认镜像启用的 FRR 协议进程")
        return expected

    def check_daemons(self, manager, item, expected):
        running = set(manager.dock("exec", item["Id"], "vtysh", "-c", "show daemons").split())
        missing = expected - running
        if missing:
            raise LabError("协议进程未运行，保留已有配置: " + ", ".join(sorted(missing)))

    def linked(self, manager, record, node):
        item = self.ready(manager, record, node)
        manager.dock("exec", "-u", "0", item["Id"], "vtysh", "-C", "-f", "/etc/frr/frr.conf")
        manager.dock("exec", "-u", "0", item["Id"], "vtysh", "-b")

    def config_status(self, manager, record, node):
        root, directory = self.paths(manager, record, node)
        metadata = self.metadata(root)
        persisted = bool(metadata) and (directory / "frr.conf").is_file()
        path = directory / "frr.conf"
        return {"supported": True, "persisted": persisted, "saved_at": metadata.get("saved_at"),
                "modified_at": path.stat().st_mtime if persisted else None,
                "path": str(directory), "content": text_file(path) if persisted else ""}

    def save_config(self, manager, record, node):
        item = manager.live(record, node["id"])
        root, directory = self.paths(manager, record, node)
        mounted = any(mount.get("Type") == "bind" and mount.get("Destination") == "/etc/frr"
                      and mount.get("Source") == str(directory) and mount.get("RW")
                      for mount in item.get("Mounts", []))
        # Old deployments can be exported before recreating them with a bind mount.
        if any(m.get("Destination") == "/etc/frr" for m in item.get("Mounts", [])) and not mounted:
            raise LabError("设备配置挂载与当前实验不匹配，拒绝保存")
        self.check_daemons(manager, item, self.required_daemons(manager, item))
        running_config = manager.dock("exec", item["Id"], "vtysh", "-c", "show running-config")
        if len(running_config) > 32768:
            raise LabError("FRR 配置超过当前拓扑的 32 KiB 字符上限")
        if mounted:
            self.backup(root, directory)
        output = manager.dock("exec", "-u", "0", item["Id"], "vtysh", "-w")
        if re.search(r"(?im)^%|failed|can't|cannot|error", output):
            raise LabError("FRR 保存失败: " + output[-1000:])
        manager.live(record, node["id"])
        if not mounted:
            self.prepare(manager, record, node)
            metadata = self.metadata(root)
            self.backup(root, directory)
            for name in self.files:
                value = manager.dock("exec", item["Id"], "sh", "-c", 'if [ -f "$1" ]; then cat "$1"; fi', "config-read", "/etc/frr/" + name)
                if value:
                    replace_text(directory / name, value.rstrip() + "\n", metadata["uid"], metadata["gid"])
        config = text_file(directory / "frr.conf").strip()
        if not config:
            raise LabError("FRR 未生成有效配置文件")
        metadata = self.metadata(root)
        metadata.update(seed_hash=seed_hash({"config": config}), saved_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.write_metadata(root, metadata)
        node["config"] = config
        return {**self.config_status(manager, record, node), "shared": mounted}


ADAPTERS = {"frr": FrrAdapter(), "linux": DeviceAdapter(), "linux-bridge": BridgeAdapter()}


def adapter_for(node):
    return ADAPTERS[template_for(node)["adapter"]]
