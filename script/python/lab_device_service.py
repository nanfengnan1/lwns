"""Device package jobs and uploads, shared by HTTP and the device CLI."""
import copy
import json
from pathlib import Path
import re
import shutil
import threading
import time
import uuid

from lab_core import atomic_json, stamp
from lab_devices import LabError
from lab_device_packages import DeviceLibrary, extract_package, inspect_package, pack_device
from lab_device_schema import validate_descriptor
from lab_images import ID, MAX_UPLOAD, ImageService, reference


class DevicePackageService(ImageService):
    """Reuse the bounded upload/command transport, with a separate device registry."""

    def __init__(self, manager, images=None, command=None, max_upload=MAX_UPLOAD):
        self.manager = manager
        self.images = images or ImageService(manager, max_upload=max_upload)
        self.library = getattr(manager, "device_library", None) or DeviceLibrary(manager.directory)
        manager.device_library = self.library
        self.directory = manager.directory / "device-packages"
        self.uploads = self.directory / "uploads"
        self.jobs_dir = self.directory / "jobs"
        self.artifacts = self.directory / "artifacts"
        for folder in (self.directory, self.uploads, self.jobs_dir, self.artifacts):
            if folder.is_symlink():
                raise LabError("设备包工作目录不能是符号链接")
            folder.mkdir(parents=True, exist_ok=True)
        self.path = manager.directory / "device-library" / "registry.json"
        self.lock = threading.RLock()
        self.command = command or self.run_command
        self.max_upload = max_upload
        self.active = None
        self.jobs = {}
        self.inventory_error = ""
        self.available = False
        self.present_ids = set()
        for path in self.jobs_dir.glob("*.json"):
            if not ID.fullmatch(path.stem) or path.is_symlink():
                continue
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["id"] != path.stem:
                    continue
                if job["state"] in ("queued", "running"):
                    job.update(state="error", error="服务重启，设备包任务中断，请检查后重试", finished_at=stamp())
                    atomic_json(path, job)
                self.jobs[job["id"]] = job
            except (OSError, ValueError, KeyError):
                continue
        for folder in (self.uploads, self.jobs_dir):
            for path in folder.iterdir():
                if ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)

    def create_upload(self, payload):
        size, name, kind = payload.get("size"), payload.get("name"), payload.get("kind")
        if type(size) is not int or not 0 < size <= self.max_upload:
            raise LabError("上传大小无效或超过上限")
        if (not isinstance(name, str) or not name or len(name) > 255
                or any(ord(c) < 32 for c in name) or "/" in name or "\\" in name):
            raise LabError("上传文件名无效")
        suffix = {"package": (".lwns", ".rov"), "archive": (".tar",)}.get(kind)
        if not suffix or not name.lower().endswith(suffix):
            raise LabError("设备包需要 .lwns（兼容旧 .rov），镜像归档仅支持未压缩 .tar")
        with self.lock:
            self.prune_uploads()
            if sum(1 for _ in self.uploads.iterdir()) >= 8:
                raise LabError("临时上传数量已达上限，请清理不用的上传")
            if shutil.disk_usage(self.uploads).free < size + 64 * 1024 ** 2:
                raise LabError("宿主机临时目录空间不足")
            upload_id = uuid.uuid4().hex
            path = self.upload_path(upload_id)
            path.mkdir(mode=0o700)
            info = {"id": upload_id, "name": name, "size": size, "kind": kind,
                    "state": "created", "created": time.time()}
            atomic_json(path / "upload.json", info)
            return info

    def ready_upload(self, upload_id, kind):
        info = self.upload_info(upload_id)
        if info["state"] != "ready" or info["kind"] != kind:
            raise LabError("请先完成对应文件上传")
        path = self.upload_path(upload_id) / "data"
        if path.is_symlink() or not path.is_file() or path.stat().st_size != info["size"]:
            raise LabError("上传资源无效，请重新上传")
        return path

    def inspect_upload(self, payload):
        if set(payload) != {"upload_id"}:
            raise LabError("检查设备包只接受 upload_id")
        with self.lock:
            return inspect_package(self.ready_upload(payload["upload_id"], "package"))

    def refresh(self):
        try:
            self.images.authorize()
            actual = self.images.inventory()
            ids = {item["image_id"] for item in actual.values()}
            self.present_ids = ids
            self.available, self.inventory_error = True, ""
        except (LabError, OSError) as exc:
            self.present_ids = set()
            self.available, self.inventory_error = False, str(exc)

    def snapshot(self, refresh=False):
        if refresh:
            self.refresh()
        with self.lock:
            entries = [{**entry, "present": entry.get("image_id") in self.present_ids}
                       for entry in self.library.entries()]
            return copy.deepcopy({"devices": entries,
                                  "jobs": sorted(self.jobs.values(), key=lambda job: job["created_at"], reverse=True)[:30],
                                  "busy": self.active is not None, "available": self.available,
                                  "error": self.inventory_error, "registry_path": str(self.path),
                                  "max_upload_bytes": self.max_upload})

    def catalog(self):
        entries = {item["id"]: item for item in self.snapshot()["devices"]}
        return [{**item, "present": entries[item["id"]]["present"]}
                for item in self.library.catalog()
                if item["id"] in entries and (entries[item["id"]]["present"] or self.manager.preview)]

    @staticmethod
    def display_name(value):
        if not isinstance(value, str) or len(value) > 80 or any(ord(c) < 32 for c in value):
            raise LabError("设备名称需为不超过 80 字符的单行文本")
        return value.strip()

    def start(self, payload):
        mode = payload.get("mode")
        name = self.display_name(payload.get("name", ""))
        spec = {"mode": mode, "name": name}
        if mode == "import":
            self.images.authorize()
            spec["upload"] = payload.get("upload_id")
            kind = "package"
        elif mode == "pack":
            descriptor = copy.deepcopy(payload.get("descriptor"))
            source = payload.get("source")
            if not isinstance(descriptor, dict) or not isinstance(source, dict):
                raise LabError("制作设备包需要设备描述和镜像来源")
            source_type = source.get("type")
            if source_type not in ("repository", "local", "archive", "dockerfile"):
                raise LabError("未知镜像来源")
            if name:
                descriptor["name"] = name
            if source.get("reference"):
                descriptor["image"] = reference(source["reference"])
            descriptor["source"] = {"type": "archive" if source_type == "local" else source_type}
            if source_type in ("local", "archive"):
                descriptor["source"]["path"] = "image.tar"
            elif source_type == "dockerfile":
                descriptor["source"]["path"] = "Dockerfile"
            spec["descriptor"] = validate_descriptor(descriptor)
            spec["source"] = source_type
            if source_type == "archive":
                spec["upload"] = source.get("upload_id")
                kind = "archive"
            elif source_type == "dockerfile":
                content = source.get("dockerfile")
                if not isinstance(content, str) or not content.strip() or "\0" in content or len(content.encode()) > 512 * 1024:
                    raise LabError("Dockerfile 不能为空或超过 512 KiB")
                spec["dockerfile"] = content
            elif source_type == "local":
                self.images.authorize()
        else:
            raise LabError("未知设备包操作")
        with self.manager.lock, self.lock:
            if self.active or self.manager.busy or self.manager.image_busy:
                raise LabError("已有设备包、镜像或部署任务执行中，请稍后重试")
            if "upload" in spec:
                self.ready_upload(spec["upload"], kind)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "mode": mode, "label": name or mode, "state": "queued",
                   "created_at": stamp(), "finished_at": None, "logs": "", "error": "", "result": None}
            if "upload" in spec:
                info = self.upload_info(spec["upload"])
                info["state"] = "in_use"
                atomic_json(self.upload_path(spec["upload"]) / "upload.json", info)
            self.jobs[job_id] = job
            atomic_json(self.jobs_dir / (job_id + ".json"), job)
            self.active, self.manager.image_busy = job_id, True
            threading.Thread(target=self.work, args=(job_id, spec), name="device-package-job-" + job_id, daemon=False).start()
            return copy.deepcopy(job)

    def image_info(self, ref):
        try:
            info = json.loads(self.manager.dock("image", "inspect", ref))[0]
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", info["Id"]):
                raise ValueError()
            if info.get("Os", "linux") != "linux":
                raise LabError("设备包需要 Linux 容器镜像")
            return info
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LabError("无法确认设备镜像的实际内容标识") from exc

    def prepare_image(self, job_id, descriptor, work):
        source, ref = descriptor["source"], descriptor["image"]
        platform = ["--platform", descriptor["platform"]] if descriptor.get("platform") else []
        if source["type"] == "repository":
            try:
                info = self.image_info(ref)
                self.check_platform(info, descriptor)
                return info
            except LabError:
                self.command(job_id, ["pull", *platform, ref])
        elif source["type"] == "archive":
            self.command(job_id, ["load", "--input", str(work / "image.tar")])
        else:
            self.command(job_id, ["build", *platform, "--tag", ref, "--file", str(work / "Dockerfile"), str(work)])
        info = self.image_info(ref)
        self.check_platform(info, descriptor)
        return info

    @staticmethod
    def check_platform(info, descriptor):
        platform = descriptor.get("platform")
        if platform:
            actual = info.get("Os", "") + "/" + info.get("Architecture", "")
            if info.get("Variant"):
                actual += "/" + info["Variant"]
            if actual != platform:
                raise LabError("镜像平台不匹配，要求 " + platform + "，实际 " + actual)

    def import_package(self, job_id, path, work, name):
        info = inspect_package(path)
        existing = next((entry for entry in self.library.entries() if entry["id"] == info["template_id"]), None)
        if existing:
            if existing["package_sha256"] != info["package_sha256"]:
                raise LabError("同一设备版本已有不同内容，请提高版本号后重新制作")
            try:
                self.image_info(existing["image_id"])
            except LabError:
                self.log(job_id, "已安装版本的镜像缺失，重新准备。\n")
            else:
                return self.library.rename(existing["id"], name) if name else existing
        self.log(job_id, "校验设备包并准备镜像…\n")
        extract_package(path, work)
        image = self.prepare_image(job_id, info["descriptor"], work)
        if existing and existing["image_id"] != image["Id"]:
            raise LabError("镜像引用已指向不同内容；请恢复原镜像，或发布新的设备版本")
        # Validate first, prepare the image, then publish the library entry.
        entry = self.library.register(path, name=name, image_id=image["Id"])
        self.log(job_id, "设备已加入设备库；项目配置和运行设备保持独立。\n")
        return entry

    def work(self, job_id, spec):
        work = self.jobs_dir / job_id
        try:
            work.mkdir(mode=0o700)
            with self.lock:
                self.jobs[job_id]["state"] = "running"
            if spec["mode"] == "import":
                entry = self.import_package(job_id, self.upload_path(spec["upload"]) / "data", work, spec["name"])
                result = {"device": entry}
            else:
                descriptor = spec["descriptor"]
                image_tar, dockerfile = None, None
                if spec["source"] == "local":
                    image = self.image_info(descriptor["image"])
                    image_tar = work / "image.tar"
                    self.command(job_id, ["save", "--output", str(image_tar), descriptor["image"]])
                    # Detect a tag changing while the export ran.
                    if self.image_info(descriptor["image"])["Id"] != image["Id"]:
                        raise LabError("导出期间镜像标签发生变化，请重新制作")
                elif spec["source"] == "archive":
                    image_tar = self.upload_path(spec["upload"]) / "data"
                elif spec["source"] == "dockerfile":
                    dockerfile = work / "Dockerfile"
                    dockerfile.write_text(spec["dockerfile"], encoding="utf-8")
                filename = descriptor["id"] + "-" + descriptor["version"] + ".lwns"
                output = self.artifacts / (job_id + ".lwns")
                self.log(job_id, "校验描述和资源，生成设备包…\n")
                pack_device(descriptor, output, image_tar=image_tar, dockerfile=dockerfile)
                result = {"download_url": "/api/device-packages/artifacts/" + job_id,
                          "filename": filename, "path": str(output)}
                self.log(job_id, "设备包已保存，可下载或另行导入。\n")
            with self.lock:
                self.jobs[job_id].update(state="success", result=result)
        except Exception as exc:
            message = str(exc)
            self.log(job_id, "失败：" + message + "\n")
            with self.lock:
                self.jobs[job_id].update(state="error", error=message)
        finally:
            try:
                if "upload" in spec:
                    with self.lock:
                        if self.jobs[job_id]["state"] == "success" or spec["mode"] == "pack":
                            # Successful uploads are already in the library/artifact.
                            # Makers retain their local File and reupload on retry.
                            shutil.rmtree(self.upload_path(spec["upload"]))
                        else:
                            # The import UI retains this id for an explicit retry.
                            info = self.upload_info(spec["upload"])
                            info["state"] = "ready"
                            atomic_json(self.upload_path(spec["upload"]) / "upload.json", info)
                shutil.rmtree(work, ignore_errors=True)
                self.refresh()
            finally:
                with self.manager.lock, self.lock:
                    self.jobs[job_id]["finished_at"] = stamp()
                    self.active, self.manager.image_busy = None, False
                    atomic_json(self.jobs_dir / (job_id + ".json"), self.jobs[job_id])

    def artifact(self, job_id):
        with self.lock:
            if not isinstance(job_id, str) or not ID.fullmatch(job_id):
                raise LabError("设备包任务标识无效")
            job = self.jobs.get(job_id)
            path = self.artifacts / (job_id + ".lwns")
            if not path.exists() and not path.is_symlink():
                path = self.artifacts / (job_id + ".rov")
            if (not job or job["mode"] != "pack" or job["state"] != "success"
                    or path.is_symlink() or not path.is_file()):
                raise LabError("设备包不存在或尚未制作完成")
            return path, job["result"]["filename"]

    def rename(self, template_id, payload):
        if set(payload) != {"name"} or not self.display_name(payload["name"]):
            raise LabError("设备名称不能为空，只接受 name 字段")
        with self.manager.lock, self.lock:
            if self.active or self.manager.busy or self.manager.image_busy:
                raise LabError("已有操作执行中，请稍后重试")
            return self.library.rename(template_id, payload["name"].strip())

    def remove(self, template_id):
        with self.manager.lock, self.lock:
            if self.active or self.manager.busy or self.manager.image_busy:
                raise LabError("已有操作执行中，请稍后重试")
            referenced = set()
            for path in self.manager.directory.glob("*.json"):
                record = self.manager.read(path.stem)
                referenced.update(node.get("template") for node in record["topology"]["nodes"])
            self.library.remove(template_id, referenced=referenced)

    def import_file(self, path, name=""):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise LabError("设备包文件不存在或不是普通文件")
        info = self.create_upload({"name": path.name, "size": path.stat().st_size, "kind": "package"})
        try:
            self.begin_upload(info["id"])
            target = self.upload_path(info["id"]) / "data"
            shutil.copyfile(path, target)
            self.finish_upload(info["id"], target.stat().st_size)
            job = self.start({"mode": "import", "upload_id": info["id"], "name": name})
            self.wait()
            result = self.jobs[job["id"]]
            if result["state"] != "success":
                raise LabError(result["error"])
            return result["result"]["device"]
        finally:
            # CLI callers cannot reuse the temporary upload id. Only the Web
            # workflow retains a ready upload to support an explicit retry.
            self.wait()
            self.discard_upload(info["id"], failed=True)

    def wait(self):
        for thread in threading.enumerate():
            if thread.name.startswith("device-package-job-"):
                thread.join()
