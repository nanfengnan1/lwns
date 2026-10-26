"""Validated, versioned device descriptions. This module never executes actions."""
import copy
import hashlib
import json
import math
from pathlib import PurePosixPath
import re

from lab_errors import LabError


DESCRIPTOR_LIMIT = 1024 * 1024
KINDS = ("router", "switch", "host", "firewall")


def object_keys(value, allowed, label):
    if not isinstance(value, dict):
        raise LabError(label + " 必须是 JSON 对象")
    extra = set(value) - set(allowed)
    if extra:
        raise LabError(label + " 包含未知字段: " + ", ".join(sorted(extra)))
    return value


def text(value, label, maximum=255):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise LabError(label + " 不能为空、包含控制字符或超过长度限制")
    return value.strip()


def number(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise LabError(label + " 超出允许范围")
    return value


def command(value, label):
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise LabError(label + " 必须是非空命令参数数组")
    result = []
    for item in value:
        if not isinstance(item, str) or len(item) > 8192 or "\0" in item:
            raise LabError(label + " 包含无效命令参数")
        result.append(item)
    if not result[0] or result[0].startswith("-"):
        raise LabError(label + " 缺少有效程序名称")
    return result


def container_path(value, label):
    value = text(value, label, 1024)
    path = PurePosixPath(value)
    if (not value.startswith("/") or value == "/" or "\\" in value or "," in value or "//" in value
            or any(part in (".", "..") for part in value.split("/")[1:]) or str(path) != value):
        raise LabError(label + " 必须是规范的容器内绝对路径")
    return value


def path_list(value, label):
    if not isinstance(value, list) or len(value) > 128:
        raise LabError(label + " 必须是最多 128 项的路径数组")
    result = [container_path(item, label) for item in value]
    if len(set(result)) != len(result):
        raise LabError(label + " 包含重复路径")
    return result


def action(value, label, ready=False):
    allowed = {"exec", "timeout_seconds", "user", "expected_files", "contains", "name"}
    if ready:
        allowed.add("interval_seconds")
    object_keys(value, allowed, label)
    result = {"exec": command(value.get("exec"), label),
              "timeout_seconds": number(value.get("timeout_seconds", 30), label + " 超时", 0.1, 3600)}
    if "name" in value:
        result["name"] = text(value["name"], label + " 名称", 80)
    if "user" in value:
        user = text(value["user"], label + " 用户", 128)
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?", user):
            raise LabError(label + " 用户格式无效")
        result["user"] = user
    if "expected_files" in value:
        result["expected_files"] = path_list(value["expected_files"], label + " 保存结果文件")
    if "contains" in value:
        values = value["contains"]
        if not isinstance(values, list) or len(values) > 64:
            raise LabError(label + " 输出检查必须是数组")
        result["contains"] = [text(item, label + " 输出检查", 1024) for item in values]
    if ready:
        result["interval_seconds"] = number(value.get("interval_seconds", 0.5), label + " 重试间隔", 0.1, 60)
    return result


def validate_descriptor(raw):
    """Return a canonical copy; reject unsupported fields rather than ignore them."""
    object_keys(raw, {"schema_version", "id", "version", "name", "category", "image", "source", "profile",
                      "console", "persistent_dirs", "startup", "actions", "description", "platform", "runtime"}, "设备描述")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise LabError("设备描述需要 schema_version: 1")
    identity = text(raw.get("id"), "设备定义 ID", 64)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identity):
        raise LabError("设备定义 ID 只允许小写字母、数字、短横线和下划线")
    version = text(raw.get("version"), "设备版本", 64)
    if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?(?:\+[A-Za-z0-9][A-Za-z0-9.-]*)?", version):
        raise LabError("设备版本需要类似 1.0 或 1.0.0 的版本号")
    category = raw.get("category")
    if category not in KINDS:
        raise LabError("设备分类必须为 router、switch、host 或 firewall")
    profile = raw.get("profile", "generic")
    if profile not in ("generic", "frr"):
        raise LabError("不支持的设备行为 profile")
    image = text(raw.get("image"), "镜像引用", 255)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]*", image) or "://" in image:
        raise LabError("镜像引用格式无效")
    if "@" in image and not re.search(r"@sha256:[a-f0-9]{64}$", image):
        raise LabError("镜像摘要需要 sha256 格式")
    source = copy.deepcopy(raw.get("source", {"type": "repository"}))
    object_keys(source, {"type", "path"}, "镜像来源")
    if source.get("type") not in ("repository", "archive", "dockerfile"):
        raise LabError("镜像来源必须为 repository、archive 或 dockerfile")
    expected = {"archive": "image.tar", "dockerfile": "Dockerfile"}.get(source["type"])
    if expected:
        if source.get("path", expected) != expected:
            raise LabError("包内镜像资源路径必须为 " + expected)
        source["path"] = expected
    elif "path" in source:
        raise LabError("仓库镜像不使用包内资源路径")
    if source["type"] == "dockerfile" and ("@" in image or image.startswith("sha256:")):
        raise LabError("Dockerfile 构建需要镜像名称和标签")
    result = {"schema_version": 1, "id": identity, "version": version,
              "name": text(raw.get("name"), "设备名称", 80), "category": category, "image": image,
              "source": source, "profile": profile,
              "console": command(raw.get("console", ["sh", "-i"]), "终端命令")}
    for optional, maximum in (("description", 2000), ("platform", 64)):
        if optional in raw:
            result[optional] = text(raw[optional], optional, maximum)
    if "platform" in result and not re.fullmatch(r"linux/[a-z0-9_]+(?:/[a-z0-9_]+)?", result["platform"]):
        raise LabError("设备镜像平台需要 linux/架构 格式")
    if "runtime" in raw:
        runtime = object_keys(raw["runtime"], {"cap_add"}, "设备运行参数")
        capabilities = runtime.get("cap_add", [])
        if (not isinstance(capabilities, list) or len(capabilities) > 1
                or any(item != "SYS_ADMIN" for item in capabilities)):
            raise LabError("runtime.cap_add 仅允许显式声明 SYS_ADMIN，供内置 FRR 等服务使用")
        result["runtime"] = {"cap_add": list(capabilities)}
    directories = raw.get("persistent_dirs")
    if not isinstance(directories, list) or not 1 <= len(directories) <= 16:
        raise LabError("设备需声明 1–16 个持久化目录")
    result["persistent_dirs"], keys, targets = [], set(), []
    for item in directories:
        object_keys(item, {"id", "target", "initialize_from", "owner", "mode", "permissions"}, "持久化目录")
        key = text(item.get("id"), "持久化目录 ID", 32)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", key) or key in keys or key in ("backups", "config-meta"):
            raise LabError("持久化目录 ID 无效或重复")
        target = container_path(item.get("target"), "持久化目录")
        if target == "/run" or any(target == reserved or target.startswith(reserved + "/") for reserved in ("/run/route-ovs", "/run/route-ovs-state")):
            raise LabError("持久化目录不能覆盖平台启动控制目录 /run/route-ovs")
        if target == "/proc" or target.startswith("/proc/") or target == "/sys" or target.startswith("/sys/") or target == "/dev" or target.startswith("/dev/"):
            raise LabError("持久化目录不能是容器系统设备目录")
        if any(target == prior or target.startswith(prior + "/") or prior.startswith(target + "/") for prior in targets):
            raise LabError("持久化挂载目录不能重复或嵌套")
        if item.get("mode", "rw") != "rw":
            raise LabError("配置保存需要可写的 rw 挂载")
        initialize = item.get("initialize_from", "image")
        if initialize not in ("image", "empty"):
            raise LabError("默认配置来源必须为 image 或 empty")
        permissions = item.get("permissions", "0750")
        if not isinstance(permissions, str) or not re.fullmatch(r"0[0-7]{3}", permissions):
            raise LabError("目录权限需要 0750 形式的八进制字符串")
        normalized = {"id": key, "target": target, "mode": "rw", "initialize_from": initialize, "permissions": permissions}
        if "owner" in item:
            owner = text(item["owner"], "配置属主", 128)
            if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?", owner):
                raise LabError("配置属主格式无效")
            normalized["owner"] = owner
        result["persistent_dirs"].append(normalized)
        keys.add(key)
        targets.append(target)
    startup = raw.get("startup")
    object_keys(startup, {"phase", "prepare", "service", "ready", "config_files"}, "启动流程")
    phase = startup.get("phase", "after_links")
    if phase not in ("after_links", "container"):
        raise LabError("启动阶段必须为 after_links 或 container")
    prepare = startup.get("prepare", [])
    if not isinstance(prepare, list) or len(prepare) > 32:
        raise LabError("启动准备最多支持 32 个步骤")
    service = startup.get("service")
    object_keys(service, {"exec"}, "服务进程")
    result["startup"] = {"phase": phase, "prepare": [action(item, "启动准备") for item in prepare],
                         "service": {"exec": command(service.get("exec"), "服务启动")},
                         "config_files": path_list(startup.get("config_files", []), "启动配置文件")}
    if "ready" in startup:
        result["startup"]["ready"] = action(startup["ready"], "就绪检查", ready=True)
    elif profile == "generic":
        raise LabError("generic 设备必须声明 startup.ready，确认实际服务启动成功")
    actions = raw.get("actions")
    object_keys(actions, {"save_config", "after_links", "after_link_added"}, "生命周期动作")
    if "save_config" not in actions:
        raise LabError("设备必须声明 actions.save_config 保存配置动作")
    result["actions"] = {key: action(value, key) for key, value in actions.items()}
    expected = result["actions"]["save_config"].setdefault("expected_files", list(result["startup"]["config_files"]))
    if not expected:
        raise LabError("保存配置必须声明 expected_files 或 startup.config_files 以验证保存结果")
    checked_paths = list(result["startup"]["config_files"])
    all_actions = list(result["actions"].values()) + result["startup"]["prepare"]
    if "ready" in result["startup"]:
        all_actions.append(result["startup"]["ready"])
    for item in all_actions:
        checked_paths.extend(item.get("expected_files", []))
    for item in checked_paths:
        if not any(item.startswith(target + "/") for target in targets):
            raise LabError("配置文件必须位于声明的持久化目录内: " + item)
    if profile == "frr":
        result["actions"]["save_config"].setdefault("user", "0")
        result["persistent_dirs"][0].setdefault("owner", "frr:frr")
        if (len(result["persistent_dirs"]) != 1 or result["persistent_dirs"][0]["id"] != "frr"
                or result["persistent_dirs"][0]["target"] != "/etc/frr"
                or result["persistent_dirs"][0]["initialize_from"] != "image"
                or result["persistent_dirs"][0]["owner"] != "frr:frr"
                or result["persistent_dirs"][0]["permissions"] != "0750"
                or result["actions"]["save_config"]["exec"] != ["vtysh", "-w"]
                or result["actions"]["save_config"]["user"] != "0"
                or not {"/etc/frr/daemons", "/etc/frr/frr.conf", "/etc/frr/vtysh.conf"}.issubset(expected)
                or result["startup"]["service"]["exec"] != ["/usr/lib/frr/docker-start"]):
            raise LabError("frr profile 需要标准 /etc/frr 持久化、docker-start 和 vtysh -w；其他设备请使用 generic")
    return result


def template_id(descriptor):
    return "rov-" + hashlib.sha256((descriptor["id"] + "@" + descriptor["version"]).encode()).hexdigest()[:24]


def json_object(data, label="设备描述"):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise LabError(label + " 包含重复 JSON 字段: " + key)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LabError(label + " 不是有效 JSON") from exc
