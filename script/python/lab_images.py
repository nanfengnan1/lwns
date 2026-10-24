"""Local Docker image inventory, streamed uploads and background import jobs."""
import copy
import errno
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
import zipfile

from lab_core import atomic_json, stamp
from lab_devices import CATALOG, LabError

ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = 8 * 1024 ** 3
MAX_CONTEXT = 16 * 1024 ** 3
MAX_LOAD_ARCHIVE = 16 * 1024 ** 3
MAX_LOG = 65536
ID = re.compile(r"^[a-f0-9]{32}$")
MANAGED_SOURCES = {"default", "archive", "url", "pull", "build", "local"}


def reference(value, tag_required=False):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,254}", value):
        raise LabError("镜像地址无效，请使用 repository:tag 或 registry.example.com/repository:tag")
    if "://" in value or value.startswith("-"):
        raise LabError("镜像地址不能是网页 URL")
    if tag_required and ("@" in value or value.startswith("sha256:")):
        raise LabError("构建镜像请填写仓库名称和标签")
    if "@" not in value and ":" not in value.rsplit("/", 1)[-1]:
        value += ":latest"
    return value


def download_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise LabError("下载地址无效")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise LabError("归档地址必须为 HTTP(S) URL，且不能包含用户名或密码")
    return value


def public_url(value):
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class ArchiveRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def extract_context(archive, directory):
    """Only regular files/directories; never let an archive escape its workspace."""
    total, count, used = 0, 0, set()

    def target(name, size):
        nonlocal total, count
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name or "\0" in name:
            raise LabError("构建上下文包含非法路径")
        result = directory.joinpath(*path.parts)
        if not result.resolve().is_relative_to(directory.resolve()):
            raise LabError("构建上下文路径越界")
        count += 1
        total += size
        if count > 100000 or total > MAX_CONTEXT:
            raise LabError("构建上下文解压后超过限制（16 GiB / 100000 项）")
        return result

    def write_file(path, stream, size, mode):
        if path in used or path.exists():
            raise LabError("构建上下文包含重复文件路径")
        used.add(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        remaining = size
        with path.open("xb") as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise LabError("构建上下文文件不完整")
                output.write(chunk)
                remaining -= len(chunk)
        os.chmod(path, 0o755 if mode & 0o111 else 0o644)

    directory.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise LabError("构建上下文不支持符号链接或特殊文件")
                path = target(item.filename, item.file_size)
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    with source.open(item) as stream:
                        write_file(path, stream, item.file_size, mode)
    else:
        with tarfile.open(archive, "r:*") as source:
            for item in source:
                if not (item.isdir() or item.isfile()):
                    raise LabError("构建上下文不支持链接、设备或其他特殊文件")
                path = target(item.name, item.size)
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    with source.extractfile(item) as stream:
                        write_file(path, stream, item.size, item.mode)


class ImageService:
    def __init__(self, manager, command=None, max_upload=MAX_UPLOAD):
        self.manager = manager
        self.directory = manager.directory / "images"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "registry.json"
        self.uploads = self.directory / "uploads"
        self.jobs_dir = self.directory / "jobs"
        self.uploads.mkdir(exist_ok=True)
        self.jobs_dir.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.command = command or self.run_command
        self.max_upload = max_upload
        self.active = None
        self.jobs = {}
        self.inventory_error = ""
        self.available = False
        if not self.path.exists():
            defaults = json.loads((ROOT / "config" / "images.defaults.json").read_text(encoding="utf-8"))
            atomic_json(self.path, {"version": 1, "images": [self.new_entry(item["reference"], item, {"type": "default"}) for item in defaults["images"]]})
        self.registry = self.read_registry()
        self.persist()
        for path in self.jobs_dir.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["state"] in ("queued", "running"):
                    job.update(state="error", error="服务重启导致任务中断，请刷新镜像清单核对实际结果", finished_at=stamp())
                    atomic_json(path, job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError):
                continue
        # Upload streams and Docker clients cannot survive a server restart.
        # Only remove service-owned UUID workspaces, never arbitrary files.
        for path in self.uploads.iterdir():
            if ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        for path in self.jobs_dir.iterdir():
            if ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
        self.prune_uploads()

    @staticmethod
    def new_entry(ref, metadata=None, source=None):
        metadata = metadata or {}
        return {"id": uuid.uuid4().hex, "reference": ref, "title": metadata.get("title") or ref,
                "template": metadata.get("template", ""), "source": source or {"type": "discovered"},
                "owned_image_id": "",
                "created_at": stamp(), "updated_at": stamp(), "present": False, "image_id": "", "size": ""}

    def read_registry(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("version") != 1 or not isinstance(value["images"], list):
                raise ValueError()
            for item in value["images"]:
                if not ID.fullmatch(item["id"]):
                    raise ValueError()
                reference(item["reference"])
                # Legacy discovery is not ownership. Keep deliberate library settings
                # as references, but discard automatically discovered host images.
                if item.get("source", {}).get("type") == "discovered" and (
                        item.get("template") or item.get("title", item["reference"]) != item["reference"]):
                    item["source"] = {"type": "local"}
                item.setdefault("owned_image_id", "")
            value["images"] = [item for item in value["images"] if self.is_managed(item)]
            return value
        except (ValueError, KeyError, TypeError) as exc:
            raise LabError("镜像清单损坏，请保留并检查 " + str(self.path)) from exc

    def persist(self):
        self.registry["updated_at"] = stamp()
        atomic_json(self.path, self.registry)

    def authorize(self):
        if self.manager.preview:
            raise LabError("设计模式不能导入、构建或删除 Docker 镜像")
        if self.manager.dock("info", "--format", "{{.OSType}}", timeout=5) != "linux":
            raise LabError("需要可访问的本机 Linux Docker daemon")

    def inventory(self):
        output = self.manager.dock("image", "ls", "--no-trunc", "--digests", "--format", "{{json .}}", timeout=15)
        result = {}
        try:
            for line in output.splitlines():
                item = json.loads(line)
                repo, tag, digest = item["Repository"], item["Tag"], item.get("Digest", "<none>")
                ref = (repo + ":" + tag) if "<none>" not in (repo, tag) else (
                    repo + "@" + digest if repo != "<none>" and digest != "<none>" else item["ID"])
                result[ref] = {"reference": ref, "image_id": item["ID"], "size": item.get("Size", ""), "present": True}
        except (ValueError, KeyError, TypeError) as exc:
            raise LabError("Docker 返回的镜像清单无效") from exc
        return result

    def sync(self):
        self.authorize()
        actual = self.inventory()
        with self.lock:
            for item in self.registry["images"]:
                state = actual.get(item["reference"])
                if item.get("owned_image_id") and (not state or state["image_id"] != item["owned_image_id"]):
                    item["owned_image_id"] = ""
                item.update(state or {"present": False, "image_id": "", "size": ""})
            self.persist()
            self.available, self.inventory_error = True, ""
        return actual

    @staticmethod
    def is_managed(item):
        return item.get("source", {}).get("type") in MANAGED_SOURCES

    @staticmethod
    def can_delete(item):
        ref = item["reference"]
        return bool(item.get("present") and item.get("owned_image_id")
                    and item["owned_image_id"] == item.get("image_id")
                    and not ref.startswith("sha256:") and "@" not in ref)

    def snapshot(self, refresh=False):
        if refresh:
            try:
                self.sync()
            except (LabError, OSError) as exc:
                self.available, self.inventory_error = False, str(exc)
        with self.lock:
            return copy.deepcopy({"images": [{**item, "can_delete": self.can_delete(item)} for item in self.registry["images"] if self.is_managed(item)], "jobs": sorted(self.jobs.values(), key=lambda job: job["created_at"], reverse=True)[:30],
                                  "busy": self.active is not None, "available": self.available, "error": self.inventory_error,
                                  "registry_path": str(self.path), "max_upload_bytes": self.max_upload})

    def catalog(self):
        # Adapter definitions are not library entries. Removing a managed image
        # must also remove its card, including images used by built-in templates.
        result = []
        with self.lock:
            for entry in self.registry["images"]:
                if not self.is_managed(entry):
                    continue
                base = next((item for item in CATALOG if item["id"] == entry["template"]), None)
                if not base or (not entry["present"] and not self.manager.preview):
                    continue
                result.append({**copy.deepcopy(base), "id": "img-" + entry["id"][:24], "template_id": base["id"],
                               "title": entry["title"], "image": entry["reference"], "source": "image", "present": entry["present"]})
        return result

    def metadata(self, payload):
        title = payload.get("title", "")
        template = payload.get("template", "")
        if not isinstance(title, str) or len(title) > 80 or "\0" in title:
            raise LabError("镜像显示名称不能超过 80 字符")
        if template not in ("", *(item["id"] for item in CATALOG)):
            raise LabError("未知设备模板")
        return {"title": title.strip(), "template": template}

    def update(self, item_id, payload):
        metadata = self.metadata(payload)
        with self.lock:
            item = self.entry(item_id)
            item.update(metadata, updated_at=stamp())
            if not item["title"]:
                item["title"] = item["reference"]
            self.persist()
            return copy.deepcopy(item)

    def entry(self, item_id):
        item = next((item for item in self.registry["images"] if item["id"] == item_id and self.is_managed(item)), None)
        if item is None:
            raise LabError("镜像记录不存在")
        return item

    def upload_path(self, upload_id):
        if not isinstance(upload_id, str) or not ID.fullmatch(upload_id):
            raise LabError("上传标识无效")
        path = self.uploads / upload_id
        if path.is_symlink():
            raise LabError("上传目录无效")
        return path

    def upload_info(self, upload_id):
        try:
            return json.loads((self.upload_path(upload_id) / "upload.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LabError("上传文件不存在或已失效，请重新上传") from exc

    def create_upload(self, payload):
        self.authorize()
        size, name, kind = payload.get("size"), payload.get("name"), payload.get("kind")
        if type(size) is not int or not 0 < size <= self.max_upload:
            raise LabError("上传大小无效或超过上限")
        if not isinstance(name, str) or not name or len(name) > 255 or any(ord(c) < 32 for c in name):
            raise LabError("上传文件名无效")
        if kind not in ("archive", "context"):
            raise LabError("上传类型无效")
        with self.lock:
            self.prune_uploads()
            if sum(1 for _ in self.uploads.iterdir()) >= 8:
                raise LabError("临时上传数量已达上限，请清理不用的上传或等待任务完成")
            if shutil.disk_usage(self.uploads).free < size + 64 * 1024 ** 2:
                raise LabError("宿主机临时目录空间不足")
            upload_id = uuid.uuid4().hex
            path = self.upload_path(upload_id)
            path.mkdir(mode=0o700)
            info = {"id": upload_id, "name": name, "size": size, "kind": kind, "state": "created", "created": time.time()}
            atomic_json(path / "upload.json", info)
            return info

    def begin_upload(self, upload_id):
        with self.lock:
            info = self.upload_info(upload_id)
            if info["state"] != "created":
                raise LabError("该上传已开始或已被使用")
            info["state"] = "uploading"
            atomic_json(self.upload_path(upload_id) / "upload.json", info)
            return info

    def finish_upload(self, upload_id, size):
        with self.lock:
            info = self.upload_info(upload_id)
            if size != info["size"]:
                raise LabError("上传文件大小不一致，请重新上传")
            info["state"] = "ready"
            atomic_json(self.upload_path(upload_id) / "upload.json", info)
            return info

    def discard_upload(self, upload_id, failed=False):
        with self.lock:
            path = self.upload_path(upload_id)
            if not path.exists():
                return
            info = self.upload_info(upload_id)
            if info["state"] == "in_use" or (info["state"] == "uploading" and not failed):
                raise LabError("上传文件正在使用")
            shutil.rmtree(path)

    def prune_uploads(self):
        for path in self.uploads.iterdir():
            if not ID.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
                continue
            try:
                info = self.upload_info(path.name)
                if time.time() - info["created"] > 86400 and info["state"] not in ("uploading", "in_use"):
                    shutil.rmtree(path)
            except (LabError, KeyError, TypeError):
                continue

    def start(self, payload):
        self.authorize()
        mode = payload.get("mode")
        metadata = self.metadata(payload)
        spec = {"mode": mode, "metadata": metadata}
        if mode in ("pull", "local"):
            spec["reference"] = reference(payload.get("reference"))
        elif mode == "url":
            spec["url"] = download_url(payload.get("url"))
        elif mode == "archive":
            spec["upload"] = payload.get("upload")
        elif mode == "build":
            spec["reference"] = reference(payload.get("reference"), tag_required=True)
            content = payload.get("dockerfile")
            if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 512 * 1024 or "\0" in content:
                raise LabError("Dockerfile 不能为空或超过 512 KiB")
            spec["dockerfile"] = content
            if payload.get("upload"):
                spec["upload"] = payload["upload"]
        elif mode in ("delete", "forget"):
            spec["item_id"] = payload.get("id")
        else:
            raise LabError("未知镜像操作")
        with self.manager.lock, self.lock:
            if self.active or self.manager.busy:
                raise LabError("已有镜像或部署任务执行中，请稍后重试")
            if mode in ("delete", "forget"):
                spec["reference"] = self.entry(spec["item_id"])["reference"]
            if "upload" in spec:
                info = self.upload_info(spec["upload"])
                if info["state"] != "ready" or info["kind"] != ("context" if mode == "build" else "archive"):
                    raise LabError("请先完成对应文件上传")
                spec["filename"] = info["name"]
            job = {"id": uuid.uuid4().hex, "mode": mode, "state": "queued", "created_at": stamp(), "finished_at": None,
                   "label": spec.get("reference") or spec.get("filename") or public_url(spec.get("url", "")), "logs": "", "error": "", "images": []}
            if "upload" in spec:
                info["state"] = "in_use"
                atomic_json(self.upload_path(spec["upload"]) / "upload.json", info)
            self.jobs[job["id"]] = job
            atomic_json(self.jobs_dir / (job["id"] + ".json"), job)
            self.active = job["id"]
            self.manager.image_busy = True
            threading.Thread(target=self.work, args=(job["id"], spec), name="image-job-" + job["id"], daemon=False).start()
            return copy.deepcopy(job)

    def log(self, job_id, message):
        with self.lock:
            job = self.jobs[job_id]
            job["logs"] = (job["logs"] + message)[-MAX_LOG:]

    def run_command(self, job_id, args):
        argv = self.manager.docker + args
        self.log(job_id, "$ docker " + " ".join(args[:4]) + "\n")
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                start_new_session=os.name != "nt")
        timed_out = threading.Event()

        def timeout():
            timed_out.set()
            try:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(3600, timeout)
        timer.start()
        output = ""
        try:
            while True:
                chunk = proc.stdout.read1(4096)
                if not chunk:
                    break
                value = chunk.decode("utf-8", "replace")
                output = (output + value)[-1024 * 1024:]
                self.log(job_id, value)
            code = proc.wait()
            if timed_out.is_set():
                raise LabError("镜像任务超过 60 分钟，请刷新清单核对实际结果")
            if code:
                raise LabError(output[-3000:].strip() or "Docker 镜像操作失败")
            return output
        finally:
            timer.cancel()
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def download(self, job_id, url, path):
        self.log(job_id, "下载归档：" + public_url(url) + "\n")
        opener = build_opener(ArchiveRedirects())
        received, previous, started = 0, 0, time.monotonic()
        with opener.open(Request(url, headers={"User-Agent": "route-ovs-image-manager"}), timeout=30) as response, path.open("wb") as output:
            length = response.headers.get("Content-Length")
            if length and int(length) > self.max_upload:
                raise LabError("远程归档超过上传大小限制")
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > self.max_upload or time.monotonic() - started > 3600:
                    raise LabError("远程归档超过大小或下载时间限制")
                output.write(chunk)
                if received - previous >= 16 * 1024 ** 2:
                    self.log(job_id, f"已下载 {received // (1024 ** 2)} MiB\n")
                    previous = received
        if not received or (length and received != int(length)):
            raise LabError("下载归档为空或不完整")

    def ensure_unused(self, ref, image_id):
        for path in self.manager.directory.glob("*.json"):
            record = self.manager.read(path.stem)
            if any(reference(node["image"]) in (ref, image_id) for node in record["topology"]["nodes"]):
                raise LabError("镜像被实验引用，请先修改或删除实验：" + record["topology"]["name"])
        cids = self.manager.dock("ps", "-aq").split()
        for cid in cids:
            item = self.manager.inspect(cid)
            if item.get("Image") == image_id or item.get("Config", {}).get("Image") == ref:
                raise LabError("镜像被容器使用，请先清理对应容器：" + item.get("Name", cid).lstrip("/"))

    def prepare_load_archive(self, job_id, archive, work):
        # Uploads and URL downloads have no extension; identify XZ by its header.
        with archive.open("rb") as source:
            if source.read(6) != b"\xfd7zXZ\x00":
                return archive
        target = work / "image.tar"
        self.log(job_id, "检测到 XZ 压缩格式，正在解压镜像归档…\n")
        total, previous, started = 0, 0, time.monotonic()
        try:
            with lzma.open(archive, "rb", format=lzma.FORMAT_XZ) as source, target.open("xb") as output:
                while True:
                    if time.monotonic() - started > 3600:
                        raise LabError("XZ 解压超过 60 分钟，请检查归档或宿主机负载")
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_LOAD_ARCHIVE:
                        raise LabError("XZ 镜像归档解压后超过 16 GiB 上限")
                    if shutil.disk_usage(work).free < len(chunk) + 64 * 1024 ** 2:
                        raise LabError("宿主机临时目录空间不足，无法解压 XZ 镜像归档")
                    output.write(chunk)
                    if total - previous >= 16 * 1024 ** 2:
                        self.log(job_id, f"已解压 {total // (1024 ** 2)} MiB\n")
                        previous = total
        except (lzma.LZMAError, EOFError) as exc:
            raise LabError("XZ 归档损坏或不完整，请重新导出或上传镜像") from exc
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise LabError("宿主机临时目录空间不足，无法解压 XZ 镜像归档") from exc
            raise
        if not total:
            raise LabError("XZ 解压结果为空，请上传 Docker 镜像归档")
        self.log(job_id, f"XZ 解压完成：{total / (1024 ** 2):.2f} MiB，开始加载 Docker 镜像。\n")
        return target

    def work(self, job_id, spec):
        work = self.jobs_dir / job_id
        try:
            work.mkdir(mode=0o700)
            with self.lock:
                self.jobs[job_id]["state"] = "running"
            before = self.sync()
            owned_before = {item["reference"]: item.get("owned_image_id", "") for item in self.registry["images"]}
            mode = spec["mode"]
            source = {"type": mode}
            refs = []
            if mode in ("delete", "forget"):
                ref = spec["reference"]
                if mode == "delete":
                    if not self.can_delete(self.entry(spec["item_id"])):
                        raise LabError("该镜像不属于本项目可删除的标签，或标签已在外部变化；只能移出管理清单，保留本地镜像")
                    self.ensure_unused(ref, before.get(ref, {}).get("image_id", ""))
                    self.command(job_id, ["image", "rm", ref])
                else:
                    self.log(job_id, "仅移出管理清单，保留本地 Docker 镜像及现有实验。\n")
                with self.lock:
                    self.registry["images"] = [item for item in self.registry["images"] if item["id"] != spec["item_id"]]
                    self.persist()
                self.sync()
            elif mode == "local":
                refs = [spec["reference"]]
                if spec["reference"] not in before:
                    raise LabError("本机不存在该镜像，请填写 docker image ls 中的完整仓库名称和标签")
                self.log(job_id, "将已有镜像加入管理清单；保留本地镜像，仅建立引用。\n")
            elif mode == "pull":
                self.command(job_id, ["pull", spec["reference"]])
                refs = [spec["reference"]]
                source["reference"] = spec["reference"]
            elif mode == "build":
                context = work / "context"
                context.mkdir()
                if "upload" in spec:
                    self.log(job_id, "解压构建上下文…\n")
                    extract_context(self.upload_path(spec["upload"]) / "data", context)
                (context / "Dockerfile").write_text(spec["dockerfile"], encoding="utf-8")
                self.command(job_id, ["build", "--tag", spec["reference"], "--file", str(context / "Dockerfile"), str(context)])
                refs = [spec["reference"]]
                source["filename"] = "Dockerfile"
            else:
                if mode == "url":
                    archive = work / "image-archive"
                    self.download(job_id, spec["url"], archive)
                    source["url"] = public_url(spec["url"])
                else:
                    archive = self.upload_path(spec["upload"]) / "data"
                    source["filename"] = spec["filename"]
                archive = self.prepare_load_archive(job_id, archive, work)
                try:
                    output = self.command(job_id, ["load", "--input", str(archive)])
                except LabError as exc:
                    if "does not contain a manifest.json" in str(exc):
                        raise LabError(str(exc) + "\n归档缺少 Docker 镜像清单；请使用 docker save 导出的镜像归档。"
                                       "docker export、普通目录或再次打包的外层 tar 不能直接加载；XZ 解压不会补齐镜像清单。") from exc
                    raise
                refs = re.findall(r"(?m)^Loaded image(?: ID)?:\s*(\S+)", output)
            if mode not in ("delete", "forget"):
                actual = self.sync()
                # Only register refs reported by this operation, never inventory diffs:
                # another Docker client may create unrelated images while we run.
                wanted = set()
                for ref in refs:
                    if ref in actual:
                        wanted.add(ref)
                    else:
                        inspected = json.loads(self.manager.dock("image", "inspect", ref))[0]
                        def canonical(value):
                            return value.removeprefix("docker.io/").removeprefix("library/")
                        wanted.update(key for key, state in actual.items() if state["image_id"] == inspected["Id"]
                                      and (canonical(key) == canonical(ref) or (ref.startswith("sha256:") and key not in before)))
                with self.lock:
                    selected = []
                    for ref in sorted(wanted):
                        item = next((entry for entry in self.registry["images"] if entry["reference"] == ref), None)
                        if item is None:
                            item = self.new_entry(ref, source=source)
                            self.registry["images"].append(item)
                        prior_id = before.get(ref, {}).get("image_id", "")
                        owned = mode != "local" and (not prior_id or (owned_before.get(ref) and owned_before[ref] == prior_id))
                        item.update(actual[ref], source=source, updated_at=stamp(),
                                    owned_image_id=actual[ref]["image_id"] if owned else "")
                        if spec["metadata"]["title"]:
                            item["title"] = spec["metadata"]["title"]
                        if spec["metadata"]["template"]:
                            item["template"] = spec["metadata"]["template"]
                        selected.append(ref)
                    if not selected:
                        raise LabError("未找到已导入镜像，请刷新清单检查 Docker 实际结果")
                    self.persist()
                    self.jobs[job_id]["images"] = selected
            self.log(job_id, "镜像清单已同步。\n")
            with self.lock:
                self.jobs[job_id]["state"] = "success"
        except Exception as exc:
            # Docker may have imported part of a multi-image archive before failing.
            try:
                self.sync()
            except Exception:
                pass
            message = str(exc)
            if spec.get("url"):
                message = message.replace(spec["url"], public_url(spec["url"]))
            self.log(job_id, "失败：" + message + "\n")
            with self.lock:
                self.jobs[job_id].update(state="error", error=message)
        finally:
            if "upload" in spec:
                shutil.rmtree(self.upload_path(spec["upload"]), ignore_errors=True)
            shutil.rmtree(work, ignore_errors=True)
            with self.manager.lock, self.lock:
                job = self.jobs[job_id]
                job["finished_at"] = stamp()
                atomic_json(self.jobs_dir / (job_id + ".json"), job)
                self.active = None
                self.manager.image_busy = False

    def wait(self):
        for thread in threading.enumerate():
            if thread.name.startswith("image-job-"):
                thread.join()
