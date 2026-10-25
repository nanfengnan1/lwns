"""Execute installed, immutable device descriptions inside owned containers.

The descriptor supplies argv, never host commands or host paths. Native files
remain in per-project/per-node bind mounts. A tiny supervised bootstrap waits
for the backend's gate and then execs the service as Docker's main process.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import uuid

from lab_devices import DeviceAdapter, FrrAdapter, checked_file, device_root, replace_text, text_file
from lab_errors import LabError


MAX_CONFIG_BYTES = 256 * 1024 * 1024
MAX_CONFIG_FILE_BYTES = 64 * 1024 * 1024
MAX_CONFIG_FILES = 10000
BOOTSTRAP = """#!/bin/sh
set -eu
trap 'exit 143' TERM
trap 'exit 130' INT
remaining=600
while [ ! -f /run/route-ovs/start ]; do
  if [ "$remaining" -le 0 ]; then
    echo 'route-ovs: timed out waiting for device preparation' >&2
    exit 124
  fi
  sleep 1 &
  wait $!
  remaining=$((remaining - 1))
done
printf '%s\\n' "$$" > /run/route-ovs-state/service.pid
exec "$@"
"""
EXECUTED = """set -eu
read -r service_pid < /run/route-ovs-state/service.pid
case "$service_pid" in ''|*[!0-9]*) exit 1 ;; esac
test -r "/proc/$service_pid/cmdline"
command -v grep >/dev/null
cmdline=$(tr '\\000' '\\n' < "/proc/$service_pid/cmdline")
test -n "$cmdline"
if printf '%s\\n' "$cmdline" | grep -Fx /run/route-ovs/bootstrap.sh >/dev/null; then
  exit 1
fi
"""


def configuration_files(directory):
    """Bound and validate a tree before reading/copying container-writable data."""
    directory = Path(directory)
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise LabError("设备配置目录必须是普通目录: " + str(directory))
    if not directory.exists():
        return []
    files, size, count = [], 0, 0
    for root, dirs, names in os.walk(directory, followlinks=False):
        for name in dirs + names:
            path = Path(root) / name
            info = path.lstat()
            count += 1
            if count > MAX_CONFIG_FILES:
                raise LabError("设备配置条目过多")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LabError("设备配置不允许符号链接、硬链接或特殊文件: " + str(path))
            size += info.st_size
            if info.st_size > MAX_CONFIG_FILE_BYTES or size > MAX_CONFIG_BYTES:
                raise LabError("设备配置文件超过大小限制")
            files.append((path.relative_to(directory).as_posix(), info.st_size))
    return sorted(files)


class DescriptorAdapter(DeviceAdapter):
    def __init__(self, template):
        self.template = template
        self.definition = template["definition"]
        self.frr = FrrAdapter() if self.definition.get("profile") == "frr" else None

    def root(self, manager, record, node):
        return device_root(manager, record["topology"]["id"], node["id"])

    def directories(self, root):
        return [(entry, root / entry["id"]) for entry in self.definition["persistent_dirs"]]

    def metadata(self, root):
        raw = text_file(root / "config-meta.json")
        try:
            metadata = json.loads(raw) if raw else {}
        except ValueError as exc:
            raise LabError("设备配置元数据损坏") from exc
        if not isinstance(metadata, dict):
            raise LabError("设备配置元数据必须是对象")
        return metadata

    def identity(self, metadata):
        if metadata and metadata.get("definition") != self.template["id"]:
            raise LabError("配置目录属于其他设备定义；请创建新实例或显式迁移配置")

    def write_metadata(self, root, metadata):
        metadata.update(definition=self.template["id"], descriptor_id=self.definition["id"],
                        descriptor_version=self.definition["version"], image_id=self.template["image"])
        replace_text(root / "config-meta.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    def owner(self, manager, node, entry):
        owner = entry.get("owner", "0:0")
        if re.fullmatch(r"\d+:\d+", owner):
            return tuple(int(value) for value in owner.split(":"))
        script = """set -eu
id -u "$1"
if [ -z "$2" ]; then
  id -g "$1"
else
  case "$2" in
    *[!0-9]*) awk -F: -v group="$2" '$1 == group {print $3; found=1} END {if (!found) exit 1}' /etc/group ;;
    *) printf '%s\\n' "$2" ;;
  esac
fi
"""
        username, _, group = owner.partition(":")
        rows = manager.dock("run", "--rm", "--pull", "never", "--network", "none", "--entrypoint", "/bin/sh",
                            node["image"], "-c", script, "route-ovs-owner", username, group).splitlines()
        try:
            uid, gid = map(int, rows)
            if uid < 0 or gid < 0:
                raise ValueError()
            return uid, gid
        except (ValueError, TypeError) as exc:
            raise LabError("无法解析设备配置目录属主: " + owner) from exc

    def seed(self, manager, root, node):
        if any(path.exists() for _, path in self.directories(root)):
            raise LabError("设备配置目录初始化不完整，请保留文件并检查: " + str(root))
        seed_id = None
        try:
            with tempfile.TemporaryDirectory(prefix=".seed-", dir=root) as temporary:
                staging = Path(temporary)
                for entry, destination in self.directories(root):
                    path = staging / entry["id"]
                    path.mkdir()
                    if entry.get("initialize_from", "image") == "image":
                        if seed_id is None:
                            seed_id = manager.dock("create", "--name", "rov-seed-" + uuid.uuid4().hex,
                                                   "--network", "none", "--label", "io.route-ovs.seed=true",
                                                   "--entrypoint", "/bin/sh", node["image"], "-c", "exit 0")
                        manager.dock("cp", "--archive", seed_id + ":" + entry["target"] + "/.", str(path), timeout=120)
                    configuration_files(path)
                    uid, gid = self.owner(manager, node, entry)
                    mode = int(entry.get("permissions", "0750"), 8)
                    for folder, dirs, files in os.walk(path):
                        os.chown(folder, uid, gid)
                        os.chmod(folder, mode)
                        for name in files:
                            child = Path(folder) / name
                            os.chown(child, uid, gid)
                            # Retain executable config scripts but remove special bits.
                            os.chmod(child, child.stat().st_mode & 0o777)
                # Stage every mount first; never overwrite previously saved files.
                for entry, destination in self.directories(root):
                    (staging / entry["id"]).rename(destination)
        finally:
            if seed_id:
                manager.dock("rm", "-f", "-v", seed_id)

    def prepare(self, manager, record, node):
        root = self.root(manager, record, node)
        root.mkdir(parents=True, exist_ok=True)
        metadata = self.metadata(root)
        self.identity(metadata)
        if self.frr:
            args = self.frr.prepare(manager, record, node)
            metadata = self.metadata(root)
        else:
            if not metadata:
                self.seed(manager, root, node)
                metadata = {"saved_at": None, "template": self.template["id"]}
            args = []
            for entry, path in self.directories(root):
                if not path.is_dir():
                    raise LabError("设备持久化目录缺失: " + entry["target"])
                configuration_files(path)
                if "," in str(path):
                    raise LabError("Docker 共享配置目录路径不能含逗号")
                args += ["--mount", "type=bind,src=" + str(path) + ",dst=" + entry["target"]]
        self.write_metadata(root, metadata)
        runtime = root / ".runtime"
        if runtime.is_symlink() or (runtime.exists() and not runtime.is_dir()):
            raise LabError("设备启动目录无效")
        runtime.mkdir(mode=0o755, exist_ok=True)
        os.chmod(runtime, 0o755)
        gate = checked_file(runtime / "start")
        if gate.exists():
            gate.unlink()
        replace_text(runtime / "bootstrap.sh", BOOTSTRAP)
        os.chmod(runtime / "bootstrap.sh", 0o644)
        if "," in str(runtime):
            raise LabError("Docker 启动目录路径不能含逗号")
        return args + ["--init", "--entrypoint", "/bin/sh", "--tmpfs",
                       "/run/route-ovs-state:rw,noexec,nosuid,size=65536,mode=1777", "--mount",
                       "type=bind,src=" + str(runtime) + ",dst=/run/route-ovs,readonly=true"]

    def command(self, node):
        return ["/run/route-ovs/bootstrap.sh", *self.definition["startup"]["service"]["exec"]]

    def host_file(self, root, target):
        location = PurePosixPath(target)
        for entry, path in self.directories(root):
            base = PurePosixPath(entry["target"])
            if location.is_relative_to(base) and location != base:
                if path.is_symlink() or (path.exists() and not path.is_dir()):
                    raise LabError("设备持久化目录无效: " + target)
                relative = location.relative_to(base)
                resolved = path
                for part in relative.parts:
                    resolved = resolved / part
                    if resolved.is_symlink():
                        raise LabError("设备配置路径不允许符号链接: " + target)
                return checked_file(resolved)
        raise LabError("配置文件不在声明的持久化目录中: " + target)

    def expected_files(self, action=None):
        return (action or {}).get("expected_files") or self.definition["startup"].get("config_files", [])

    def verify_files(self, root, files):
        for target in files:
            path = self.host_file(root, target)
            if not path.is_file():
                raise LabError("设备未生成必要配置文件: " + target)

    def execute_action(self, manager, record, node, action, label, *, timeout=None):
        item = manager.live(record, node["id"])
        manager.note(record, "设备 " + node["name"] + "：" + label)
        try:
            output = manager.dock("exec", "-u", action.get("user", "0"), item["Id"], *action["exec"],
                                  timeout=timeout or action.get("timeout_seconds", 30))
            for expected in action.get("contains", []):
                if expected not in output:
                    raise LabError("输出缺少预期内容: " + expected)
            self.verify_files(self.root(manager, record, node), action.get("expected_files", []))
            if output:
                manager.note(record, "设备 " + node["name"] + " " + label + "输出：" + output[-4000:])
            return output
        except (LabError, OSError) as exc:
            raise LabError("设备 " + node["name"] + " 的" + label + "失败: " + str(exc)) from exc

    def readiness(self, manager, record, node):
        if self.frr:
            self.frr.ready(manager, record, node)
        action = self.definition["startup"].get("ready")
        if not action:
            # Generic descriptions require ready in the schema. FRR has already
            # checked its configured daemons above and may omit an extra probe.
            manager.live(record, node["id"])
            return
        deadline = time.monotonic() + action.get("timeout_seconds", 30)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LabError("设备 " + node["name"] + " 就绪检查超时")
            try:
                self.execute_action(manager, record, node, action, "就绪检查", timeout=max(0.1, remaining))
                return
            except LabError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(action.get("interval_seconds", 0.5), remaining))

    def start_service(self, manager, record, node):
        root = self.root(manager, record, node)
        for index, action in enumerate(self.definition["startup"].get("prepare", [])):
            self.execute_action(manager, record, node, action, action.get("name", "启动准备 " + str(index + 1)))
        self.verify_files(root, self.definition["startup"].get("config_files", []))
        replace_text(root / ".runtime" / "start", "start\n")
        os.chmod(root / ".runtime" / "start", 0o644)
        # The wrapper waits for the gate then execs the service; it never leaves
        # an unmonitored detached docker-exec process behind.
        deadline = time.monotonic() + 15
        while True:
            item = manager.live(record, node["id"])
            try:
                manager.dock("exec", "-u", "0", item["Id"], "/bin/sh", "-c", EXECUTED,
                             timeout=max(0.1, deadline - time.monotonic()))
                manager.live(record, node["id"])
                break
            except LabError as exc:
                if time.monotonic() >= deadline:
                    raise LabError("设备服务未进入启动阶段: " + str(exc)) from exc
                time.sleep(0.1)
        self.readiness(manager, record, node)

    def started(self, manager, record, node):
        if self.definition["startup"].get("phase", "after_links") == "container":
            self.start_service(manager, record, node)

    def linked(self, manager, record, node):
        if self.definition["startup"].get("phase", "after_links") == "after_links":
            self.start_service(manager, record, node)
        if self.frr:
            self.frr.linked(manager, record, node)
        action = self.definition["actions"].get("after_links")
        if action:
            self.execute_action(manager, record, node, action, "接线后配置")

    def link_added(self, manager, record, node):
        action = self.definition["actions"].get("after_link_added")
        if action:
            self.execute_action(manager, record, node, action, "新增连线配置")

    def config_status(self, manager, record, node):
        root = self.root(manager, record, node)
        metadata = self.metadata(root)
        self.identity(metadata)
        if self.frr:
            return self.frr.config_status(manager, record, node)
        files = []
        paths = []
        for entry, path in self.directories(root):
            paths.append(str(path))
            for name, size in configuration_files(path):
                files.append({"path": str(PurePosixPath(entry["target"]) / name), "size": size})
        return {"supported": True, "persisted": bool(metadata) and bool(files),
                "saved_at": metadata.get("saved_at"), "path": str(root), "paths": paths,
                "files": files, "content": "", "definition": self.template["id"]}

    def mounted(self, manager, record, node):
        item = manager.live(record, node["id"])
        root = self.root(manager, record, node)
        metadata = self.metadata(root)
        if not metadata:
            raise LabError("设备配置元数据缺失，请检查持久化目录")
        self.identity(metadata)
        for entry, path in self.directories(root):
            matches = [mount for mount in item.get("Mounts", []) if mount.get("Destination") == entry["target"]]
            if len(matches) != 1 or not (matches[0].get("Type") == "bind" and matches[0].get("RW")
                                         and matches[0].get("Source") == str(path)):
                raise LabError("设备配置挂载与当前实例不匹配或不可写: " + entry["target"])
            configuration_files(path)
        return root

    def save_config(self, manager, record, node):
        root = self.mounted(manager, record, node)
        if self.frr:
            action = self.definition["actions"]["save_config"]
            return self.frr.save_config(manager, record, node, action=action,
                                        verify=lambda: self.verify_files(root, self.expected_files(action)))
        self.readiness(manager, record, node)
        backup = root / "backups"
        if backup.is_symlink() or (backup.exists() and not backup.is_dir()):
            raise LabError("设备配置备份目录无效")
        backup = backup / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        for entry, path in self.directories(root):
            shutil.copytree(path, backup / entry["id"], symlinks=True)
        action = self.definition["actions"]["save_config"]
        self.execute_action(manager, record, node, action, "保存配置")
        self.mounted(manager, record, node)
        self.verify_files(root, self.expected_files(action))
        metadata = self.metadata(root)
        metadata["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.write_metadata(root, metadata)
        return {**self.config_status(manager, record, node), "shared": True}
