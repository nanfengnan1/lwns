"""Portable .lwns packages and the versioned local device library.

Packing and inspecting never start containers or run descriptor actions. Image
preparation is deliberately delegated to the service shared by Web and CLI.
"""
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile
import threading
import zipfile

from lab_errors import LabError
from lab_device_schema import DESCRIPTOR_LIMIT, json_object, template_id, text, validate_descriptor


MAX_PACKAGE = 16 * 1024 ** 3
MAX_DOCKERFILE = 512 * 1024
CHUNK = 1024 * 1024
# The .lwns v1 wire identifier is stable across the product rename to lwns.
FORMAT = "route-ovs-device"


def stamp():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordinary_file(path, label):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise LabError(label + " 必须是普通文件")
    return path


def load_descriptor(value):
    if isinstance(value, dict):
        return copy.deepcopy(value)
    path = ordinary_file(value, "设备描述")
    if path.stat().st_size > DESCRIPTOR_LIMIT:
        raise LabError("设备描述超过 1 MiB")
    return json_object(path.read_bytes())


def archive_reference(value):
    if "@" not in value and ":" not in value.rsplit("/", 1)[-1]:
        return value + ":latest"
    return value


def validate_image_archive(stream, reference):
    """Inspect a raw Docker-save tar without extracting any member to disk."""
    manifest = None
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for count, member in enumerate(archive, 1):
                if count > 100000:
                    raise LabError("镜像归档条目过多")
                if member.name == "manifest.json":
                    if manifest is not None or not member.isfile() or member.size > DESCRIPTOR_LIMIT:
                        raise LabError("镜像归档 manifest.json 重复、无效或过大")
                    content = archive.extractfile(member)
                    if content is None:
                        raise LabError("无法读取镜像归档清单")
                    manifest = json_object(content.read(DESCRIPTOR_LIMIT + 1), "镜像归档清单")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise LabError("image.tar 必须是 docker save 导出的未压缩 tar 归档") from exc
    if not isinstance(manifest, list) or not manifest:
        raise LabError("镜像归档缺少有效 manifest.json，请使用 docker save 导出")
    wanted = archive_reference(reference)
    for item in manifest:
        if not isinstance(item, dict):
            continue
        tags = item.get("RepoTags") or []
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise LabError("镜像清单 RepoTags 格式无效")
        if wanted in tags:
            return
        config = item.get("Config", "")
        if isinstance(config, str) and wanted.startswith("sha256:"):
            digest = wanted[7:]
            if re.fullmatch(r"[a-f0-9]{64}", digest) and config in (digest + ".json", "blobs/sha256/" + digest):
                return
    raise LabError("镜像归档不包含设备描述指定的镜像: " + reference)


def _zip_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def pack_device(descriptor, output, image_tar=None, dockerfile=None, overwrite=False):
    """Create a package atomically; return the same report as inspect_package."""
    raw = load_descriptor(descriptor)
    if image_tar is not None and dockerfile is not None:
        raise LabError("一次制作只能选择镜像归档或 Dockerfile 中的一种来源")
    resource = None
    if image_tar is not None:
        raw["source"] = {"type": "archive", "path": "image.tar"}
        resource = ordinary_file(image_tar, "镜像归档")
    elif dockerfile is not None:
        raw["source"] = {"type": "dockerfile", "path": "Dockerfile"}
        resource = ordinary_file(dockerfile, "Dockerfile")
    definition = validate_descriptor(raw)
    source = definition["source"]
    if source["type"] != "repository" and resource is None:
        raise LabError("制作设备包缺少来源文件: " + source["path"])
    output = Path(output)
    if output.suffix.lower() != ".lwns":
        raise LabError("设备包文件名需要 .lwns 扩展名")
    if output.is_symlink() or (output.exists() and not overwrite):
        raise LabError("输出文件已存在或不是普通文件，拒绝覆盖")
    if resource and output.resolve() == resource.resolve():
        raise LabError("输出设备包不能覆盖输入资源")
    data = canonical_json(definition)
    members = {"device.json": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}
    if resource:
        size = resource.stat().st_size
        limit = MAX_DOCKERFILE if source["type"] == "dockerfile" else MAX_PACKAGE - DESCRIPTOR_LIMIT * 2
        if not 0 < size <= limit:
            raise LabError("镜像资源为空或超过设备包大小限制")
        if source["type"] == "archive":
            with resource.open("rb") as stream:
                validate_image_archive(stream, definition["image"])
        else:
            try:
                if "\0" in resource.read_text(encoding="utf-8"):
                    raise ValueError()
            except (UnicodeError, ValueError) as exc:
                raise LabError("Dockerfile 必须是有效 UTF-8 文本") from exc
        members[source["path"]] = {"size": size, "sha256": file_hash(resource)}
    manifest = {"format": FORMAT, "version": 1, "files": members}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".lwns-", suffix=".lwns", dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(_zip_info("device.json"), data)
            archive.writestr(_zip_info("manifest.json"), canonical_json(manifest))
            if resource:
                with resource.open("rb") as incoming, archive.open(_zip_info(source["path"]), "w", force_zip64=True) as outgoing:
                    shutil.copyfileobj(incoming, outgoing, CHUNK)
        report = inspect_package(temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if output.exists() and not overwrite:
            raise LabError("输出设备包已存在，拒绝覆盖")
        os.replace(temporary, output)
        report["path"] = str(output)
        return report
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _read_package(path, destination=None):
    path = ordinary_file(path, "设备包")
    if not 0 < path.stat().st_size <= MAX_PACKAGE:
        raise LabError("设备包为空或超过大小限制")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if not 2 <= len(infos) <= 3:
                raise LabError("设备包只允许 device.json、manifest.json 和一个镜像来源文件")
            by_name = {}
            total = 0
            for item in infos:
                if item.filename not in {"device.json", "manifest.json", "image.tar", "Dockerfile"} or item.filename in by_name:
                    raise LabError("设备包包含不允许的路径或重复文件")
                mode = item.external_attr >> 16
                if item.is_dir() or (stat.S_IFMT(mode) not in (0, stat.S_IFREG)) or item.flag_bits & 1:
                    raise LabError("设备包不能包含目录、链接、特殊文件或加密资源")
                if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise LabError("设备包仅支持普通 ZIP 存储或 deflate 压缩")
                limit = MAX_DOCKERFILE if item.filename == "Dockerfile" else (MAX_PACKAGE if item.filename == "image.tar" else DESCRIPTOR_LIMIT)
                if item.file_size > limit or item.file_size < 0:
                    raise LabError("设备包成员超过大小限制")
                total += item.file_size
                if total > MAX_PACKAGE:
                    raise LabError("设备包展开内容超过大小限制")
                by_name[item.filename] = item
            if "device.json" not in by_name or "manifest.json" not in by_name:
                raise LabError("设备包缺少 device.json 或完整性清单")
            descriptor = validate_descriptor(json_object(archive.read("device.json")))
            manifest = json_object(archive.read("manifest.json"), "设备包完整性清单")
            if (not isinstance(manifest, dict) or set(manifest) != {"format", "version", "files"}
                    or manifest.get("format") != FORMAT or type(manifest.get("version")) is not int or manifest["version"] != 1):
                raise LabError("不支持的设备包格式版本")
            source = descriptor["source"]
            expected = {"device.json"}
            if source["type"] != "repository":
                expected.add(source["path"])
            files = manifest.get("files")
            if not isinstance(files, dict) or set(files) != expected or set(by_name) != expected | {"manifest.json"}:
                raise LabError("设备包资源与镜像来源或完整性清单不一致")
            for name in sorted(expected):
                metadata = files[name]
                if (not isinstance(metadata, dict) or set(metadata) != {"size", "sha256"}
                        or type(metadata["size"]) is not int or metadata["size"] != by_name[name].file_size
                        or not isinstance(metadata["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"])):
                    raise LabError("设备包完整性清单无效: " + name)
                digest, count = hashlib.sha256(), 0
                outgoing = None
                try:
                    if destination is not None:
                        target = destination / name
                        if target.exists() or target.is_symlink():
                            raise LabError("设备包解包目标已存在: " + name)
                        outgoing = target.open("xb")
                    with archive.open(name) as incoming:
                        for chunk in iter(lambda: incoming.read(CHUNK), b""):
                            count += len(chunk)
                            if count > metadata["size"]:
                                raise LabError("设备包实际资源超过清单大小")
                            digest.update(chunk)
                            if outgoing:
                                outgoing.write(chunk)
                finally:
                    if outgoing:
                        outgoing.close()
                if count != metadata["size"] or digest.hexdigest() != metadata["sha256"]:
                    raise LabError("设备包资源校验失败: " + name)
            if source["type"] == "archive":
                with archive.open("image.tar") as stream:
                    validate_image_archive(stream, descriptor["image"])
            if source["type"] == "dockerfile":
                dockerfile = archive.read("Dockerfile").decode("utf-8")
                if not dockerfile.strip() or "\0" in dockerfile:
                    raise LabError("Dockerfile 不能为空或包含 NUL")
            return {"descriptor": descriptor, "template_id": template_id(descriptor),
                    "package_sha256": file_hash(path), "resources": copy.deepcopy(files), "path": str(path)}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, UnicodeError, RuntimeError, ValueError) as exc:
        raise LabError("设备包损坏或无法读取: " + str(exc)) from exc


def inspect_package(path):
    return _read_package(path)


def extract_package(path, directory):
    """Validate first, then extract only known ordinary files to an empty folder."""
    report = inspect_package(path)
    directory = Path(directory)
    if directory.is_symlink() or (directory.exists() and (not directory.is_dir() or any(directory.iterdir()))):
        raise LabError("设备包解包目录必须为空且不能是链接")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        extracted = _read_package(path, directory)
        if report["package_sha256"] != extracted["package_sha256"]:
            raise LabError("设备包在解包期间发生变化")
        return extracted
    except BaseException:
        for name in ("device.json", "Dockerfile", "image.tar"):
            target = directory / name
            if target.is_file() and not target.is_symlink():
                target.unlink()
        raise


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".registry-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(canonical_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class DeviceLibrary:
    def __init__(self, directory):
        self.root = Path(directory) / "device-library"
        if self.root.is_symlink():
            raise LabError("设备库目录不能是符号链接")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "registry.json"
        self.lock = threading.RLock()

    def _read(self):
        if self.path.is_symlink():
            raise LabError("设备库清单不能是符号链接")
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 16 * DESCRIPTOR_LIMIT:
            raise LabError("设备库清单过大")
        data = json_object(self.path.read_bytes(), "设备库清单")
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("devices"), list):
            raise LabError("设备库清单格式无效")
        ids = set()
        for entry in data["devices"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("definition"), dict):
                raise LabError("设备库条目格式无效")
            descriptor = validate_descriptor(entry["definition"])
            if entry.get("id") != template_id(descriptor) or entry["id"] in ids:
                raise LabError("设备库设备身份无效或重复")
            ids.add(entry["id"])
        return data["devices"]

    def entries(self):
        with self.lock:
            return copy.deepcopy(self._read())

    def _entry(self, identity):
        entry = next((entry for entry in self._read() if entry["id"] == identity), None)
        if entry is None:
            raise LabError("设备定义不存在，请先导入对应版本的 .lwns")
        return entry

    def _directory(self, descriptor):
        directory = self.root
        for part in (descriptor["id"], descriptor["version"]):
            directory = directory / part
            if directory.is_symlink():
                raise LabError("设备库版本目录不能是符号链接")
        if not directory.resolve().is_relative_to(self.root.resolve()):
            raise LabError("设备库目录越界")
        return directory

    def package_path(self, identity):
        with self.lock:
            entry = self._entry(identity)
            directory = self._directory(entry["definition"])
            path = directory / "device.lwns"
            if not path.exists() and not path.is_symlink():
                path = directory / "device.rov"
            return ordinary_file(path, "已注册设备包")

    def descriptor(self, identity):
        with self.lock:
            return copy.deepcopy(self._entry(identity)["definition"])

    @staticmethod
    def _template(entry):
        definition = entry["definition"]
        kind = definition["category"]
        ports, prefix = {"router": (4, "R"), "switch": (8, "SW"), "host": (1, "PC"), "firewall": (4, "FW")}[kind]
        return {"id": entry["id"], "template_id": entry["id"], "version": definition["version"],
                "descriptor_id": definition["id"], "descriptor_version": definition["version"],
                "adapter": "descriptor", "managed": True, "source": "rov", "profile": definition["profile"],
                "kind": kind, "title": entry["name"], "image": entry["image_id"] or definition["image"],
                "image_reference": definition["image"], "image_id": entry["image_id"], "ports": ports,
                "prefix": prefix, "console": definition["console"][0], "console_command": definition["console"],
                "capabilities": {"save_config": True, "startup_config": definition["profile"] == "frr"},
                "definition": copy.deepcopy(definition)}

    def catalog(self):
        return [self._template(entry) for entry in self.entries() if entry.get("image_id")]

    def resolve(self, identity):
        with self.lock:
            entry = self._entry(identity)
            if not entry.get("image_id"):
                raise LabError("该设备版本的镜像尚未准备完成")
            return self._template(entry)

    def register(self, package_path, name="", image_id=""):
        report = inspect_package(package_path)
        definition = report["descriptor"]
        if image_id and not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise LabError("设备镜像 ID 需要完整 sha256 格式")
        display = text(name or definition["name"], "设备库名称", 80)
        with self.lock:
            entries = self._read()
            previous = next((item for item in entries if item["id"] == report["template_id"]), None)
            if previous:
                if previous["package_sha256"] != report["package_sha256"]:
                    raise LabError("该设备 ID 和版本已存在不同内容，请发布新版本")
                if image_id and previous["image_id"] and previous["image_id"] != image_id:
                    raise LabError("该设备版本已绑定不同镜像，请发布新版本")
                if image_id and not previous["image_id"]:
                    previous.update(image_id=image_id, updated_at=stamp())
                    atomic_json(self.path, {"version": 1, "devices": entries})
                return copy.deepcopy(previous)
            directory = self._directory(definition)
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / "device.lwns"
            if destination.is_symlink():
                raise LabError("设备包路径不能是符号链接")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".package-", delete=False) as stream:
                    temporary = Path(stream.name)
                    with Path(package_path).open("rb") as incoming:
                        shutil.copyfileobj(incoming, stream, CHUNK)
                    stream.flush()
                    os.fsync(stream.fileno())
                if file_hash(temporary) != report["package_sha256"]:
                    raise LabError("设备包在登记期间发生变化")
                os.replace(temporary, destination)
                now = stamp()
                entry = {"id": report["template_id"], "descriptor_id": definition["id"], "version": definition["version"],
                         "name": display, "category": definition["category"], "image": definition["image"], "image_id": image_id,
                         "package_sha256": report["package_sha256"], "created_at": now, "updated_at": now,
                         "definition": definition}
                entries.append(entry)
                atomic_json(self.path, {"version": 1, "devices": entries})
                return copy.deepcopy(entry)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()

    def rename(self, identity, name):
        display = text(name, "设备库名称", 80)
        with self.lock:
            entries = self._read()
            entry = next((item for item in entries if item["id"] == identity), None)
            if entry is None:
                raise LabError("设备定义不存在")
            entry.update(name=display, updated_at=stamp())
            atomic_json(self.path, {"version": 1, "devices": entries})
            return copy.deepcopy(entry)

    def remove(self, identity, referenced=()):
        with self.lock:
            if identity in referenced:
                raise LabError("该设备版本仍被项目引用，不能删除")
            entries = self._read()
            entry = next((item for item in entries if item["id"] == identity), None)
            if entry is None:
                raise LabError("设备定义不存在")
            directory = self._directory(entry["definition"])
            paths = [directory / "device.lwns", directory / "device.rov"]
            if any(path.is_symlink() for path in paths):
                raise LabError("设备包路径不能是符号链接")
            atomic_json(self.path, {"version": 1, "devices": [item for item in entries if item["id"] != identity]})
            # Do not remove instance configuration or Docker images. An orphaned
            # immutable archive is harmless if filesystem cleanup fails.
            for path in paths:
                if path.is_file():
                    try:
                        path.unlink()
                    except OSError:
                        pass
            return {"removed": identity}
