"""Image inventory, import jobs, streaming uploads and deletion consistency."""
import io
import json
import lzma
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from test_lab import FakeHost, LabManager, LabError, example
from lab_images import ImageService, extract_context, reference, download_url
from lab_server import create_app
from fastapi.testclient import TestClient


class ImageHost(FakeHost):
    def __init__(self):
        super().__init__()
        self.images = {"alpine/frr:latest": "sha256:" + "a" * 64, "alpine/vpcs:latest": "sha256:" + "b" * 64}
        self.fail_image = False
        self.imports = ["test/router:one", "test/router:two"]
        self.loaded_archives = []

    def __call__(self, argv, **kwargs):
        args = argv[3:]
        if argv[0] == "docker" and args[:2] == ["image", "ls"]:
            self.calls.append((argv, kwargs))
            if "{{json .}}" in args:
                output = "\n".join(json.dumps({"Repository": ref.rsplit(":", 1)[0], "Tag": ref.rsplit(":", 1)[1], "ID": image_id, "Size": "2MB"}) for ref, image_id in self.images.items())
            else:
                output = "\n".join(self.images)
            return subprocess.CompletedProcess(argv, 0, output, "")
        return super().__call__(argv, **kwargs)

    def command(self, job_id, args):
        self.calls.append((args, {}))
        if self.fail_image:
            raise LabError("simulated image failure")
        if args[0] == "pull":
            self.images[args[1]] = "sha256:" + "c" * 64
            return "Pulled\n"
        if args[0] == "load":
            self.loaded_archives.append((Path(args[-1]), Path(args[-1]).read_bytes()))
            for index, ref in enumerate(self.imports):
                self.images[ref] = "sha256:" + str(index + 1) * 64
            return "\n".join("Loaded image: " + ref for ref in self.imports)
        if args[0] == "build":
            self.images[args[args.index("--tag") + 1]] = "sha256:" + "d" * 64
            self.last_context = {str(path.relative_to(args[-1])): path.read_bytes() for path in Path(args[-1]).rglob("*") if path.is_file()}
            return "Successfully built\n"
        if args[:2] == ["image", "rm"]:
            del self.images[args[-1]]
            return "Untagged\n"
        raise AssertionError(args)


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = ImageHost()
        self.manager = LabManager(self.temp.name, runner=self.host)
        self.manager.authorize = lambda: None
        self.images = ImageService(self.manager, command=self.host.command, max_upload=1024 * 1024)

    def tearDown(self):
        self.images.wait()
        self.temp.cleanup()

    def job(self, payload):
        job = self.images.start(payload)
        self.images.wait()
        return self.images.jobs[job["id"]]

    def upload(self, content, kind="archive", name="archive.tar.xz"):
        info = self.images.create_upload({"name": name, "size": len(content), "kind": kind})
        self.images.begin_upload(info["id"])
        (self.images.upload_path(info["id"]) / "data").write_bytes(content)
        self.images.finish_upload(info["id"], len(content))
        return info["id"]

    def test_default_file_and_external_inventory_is_not_managed(self):
        self.assertTrue(self.images.path.is_file())
        self.assertEqual(self.manager.list_labs(), [])
        self.host.images["external/device:latest"] = "sha256:" + "e" * 64
        self.images.sync()
        self.assertNotIn("external/device:latest", [item["reference"] for item in self.images.snapshot()["images"]])
        self.assertNotIn("external/device:latest", self.images.path.read_text())
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == "alpine/frr:latest")
        self.assertFalse(entry["can_delete"])
        del self.host.images["alpine/frr:latest"]
        self.images.sync()
        self.assertFalse(self.images.entry(entry["id"])["present"])

    def test_pull_binds_to_existing_adapter_and_survives_restart(self):
        job = self.job({"mode": "pull", "reference": "test/frr", "template": "frr", "title": "测试 FRR"})
        self.assertEqual(job["state"], "success", job)
        card = next(item for item in self.images.catalog() if item["image"] == "test/frr:latest")
        self.assertEqual((card["template_id"], card["kind"], card["title"]), ("frr", "router", "测试 FRR"))
        restarted = ImageService(self.manager, command=self.host.command)
        self.assertIn("test/frr:latest", [item["reference"] for item in restarted.snapshot()["images"]])
        self.assertEqual(restarted.jobs[job["id"]]["state"], "success")

    def test_load_all_archive_tags_and_discard_staged_file(self):
        upload = self.upload(b"fake archive")
        job = self.job({"mode": "archive", "upload": upload, "template": "linux-host"})
        self.assertEqual(job["state"], "success", job)
        self.assertEqual(set(job["images"]), set(self.host.imports))
        self.assertFalse(self.images.upload_path(upload).exists())

    def archive_bytes(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            for name, content in (("manifest.json", b"[]"), ("layer.tar", b"layer" * 300000)):
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        return output.getvalue()

    def test_xz_upload_is_decompressed_before_load_regardless_of_name(self):
        content = self.archive_bytes()
        for name in ("image.tar.xz", "image.xz", "image.tar"):
            with self.subTest(name=name):
                upload = self.upload(lzma.compress(content), name=name)
                job = self.job({"mode": "archive", "upload": upload})
                self.assertEqual(job["state"], "success", job)
                path, loaded = self.host.loaded_archives[-1]
                self.assertEqual(loaded, content)
                self.assertEqual(path.name, "image.tar")
                self.assertIn("XZ 解压完成", job["logs"])
                self.assertFalse(path.parent.exists())
                self.assertFalse(self.images.upload_path(upload).exists())
                self.assertFalse(self.manager.image_busy)

    def test_plain_tar_and_gzip_are_passed_through_without_xz_decompression(self):
        import gzip
        content = self.archive_bytes()
        self.images.max_upload = len(content)
        for archive in (content, gzip.compress(content)):
            with self.subTest(header=archive[:6]):
                upload = self.upload(archive)
                job = self.job({"mode": "archive", "upload": upload})
                self.assertEqual(job["state"], "success", job)
                self.assertEqual(self.host.loaded_archives[-1][1], archive)
                self.assertNotIn("XZ 解压", job["logs"])

    def test_xz_url_without_extension_is_decompressed_before_load(self):
        content = self.archive_bytes()
        with patch.object(self.images, "download", side_effect=lambda job, url, path: path.write_bytes(lzma.compress(content))):
            job = self.job({"mode": "url", "url": "https://example.com/download?token=secret"})
        self.assertEqual(job["state"], "success", job)
        path, loaded = self.host.loaded_archives[-1]
        self.assertEqual(loaded, content)
        self.assertIn("XZ 解压完成", job["logs"])
        self.assertFalse(path.parent.exists())
        self.assertNotIn("secret", json.dumps(job))
        self.assertNotIn("secret", self.images.path.read_text())

    def test_invalid_xz_never_reaches_docker_and_cleans_temporary_files(self):
        compressed = lzma.compress(self.archive_bytes())
        corrupt = bytearray(compressed)
        corrupt[-5] ^= 255
        for content, message in ((compressed[:-12], "损坏或不完整"), (bytes(corrupt), "损坏或不完整"),
                                 (lzma.compress(b""), "结果为空")):
            with self.subTest(message=message, length=len(content)):
                upload = self.upload(content)
                job = self.job({"mode": "archive", "upload": upload})
                self.assertEqual(job["state"], "error", job)
                self.assertIn(message, job["error"])
                self.assertEqual(self.host.loaded_archives, [])
                self.assertFalse(any(args[0] == "load" for args, _ in self.host.calls))
                self.assertFalse(self.images.upload_path(upload).exists())
                self.assertFalse((self.images.jobs_dir / job["id"]).exists())
                self.assertFalse(self.manager.image_busy)
                self.assertFalse(any(item["reference"] in self.host.imports for item in self.images.snapshot()["images"]))

    def test_xz_size_limit_stops_before_docker_load(self):
        upload = self.upload(lzma.compress(self.archive_bytes()))
        with patch("lab_images.MAX_LOAD_ARCHIVE", 1024):
            job = self.job({"mode": "archive", "upload": upload})
        self.assertEqual(job["state"], "error", job)
        self.assertIn("解压后超过", job["error"])
        self.assertEqual(self.host.loaded_archives, [])
        self.assertFalse(self.images.upload_path(upload).exists())
        self.assertFalse((self.images.jobs_dir / job["id"]).exists())

    def test_xz_low_disk_space_stops_before_docker_load(self):
        from types import SimpleNamespace
        upload = self.upload(lzma.compress(self.archive_bytes()))
        with patch("lab_images.shutil.disk_usage", return_value=SimpleNamespace(free=64 * 1024 ** 2)):
            job = self.job({"mode": "archive", "upload": upload})
        self.assertEqual(job["state"], "error", job)
        self.assertIn("空间不足", job["error"])
        self.assertEqual(self.host.loaded_archives, [])
        self.assertFalse(self.images.upload_path(upload).exists())
        self.assertFalse((self.images.jobs_dir / job["id"]).exists())

    def test_xz_missing_manifest_reports_cause_and_cleans_decompressed_file(self):
        upload = self.upload(lzma.compress(self.archive_bytes()))
        received = []
        def command(job_id, args):
            received.append(Path(args[-1]))
            self.assertTrue(received[-1].exists())
            raise LabError("invalid archive: does not contain a manifest.json")
        self.images.command = command
        job = self.job({"mode": "archive", "upload": upload})
        self.assertEqual(job["state"], "error", job)
        self.assertIn("does not contain a manifest.json", job["error"])
        self.assertIn("docker save", job["error"])
        self.assertIn("XZ 解压完成", job["logs"])
        self.assertEqual(received[0].name, "image.tar")
        self.assertFalse(received[0].parent.exists())
        self.assertFalse(self.images.upload_path(upload).exists())
        self.assertFalse(self.manager.image_busy)

    def test_default_image_card_follows_metadata_unbinding_and_deletion(self):
        self.images.sync()
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == "alpine/frr:latest")
        self.images.update(entry["id"], {"title": "我的路由器", "template": "frr"})
        cards = [item for item in self.images.catalog() if item["image"] == entry["reference"]]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "我的路由器")
        self.assertEqual(cards[0]["template_id"], "frr")
        self.images.update(entry["id"], {"title": "仅镜像", "template": ""})
        self.assertNotIn(entry["reference"], [item["image"] for item in self.images.catalog()])
        self.images.update(entry["id"], {"title": "我的路由器", "template": "frr"})
        self.host.fail_image = True
        self.assertEqual(self.job({"mode": "delete", "id": entry["id"]})["state"], "error")
        self.assertIn(entry["reference"], [item["image"] for item in self.images.catalog()])
        self.host.fail_image = False
        self.assertEqual(self.job({"mode": "forget", "id": entry["id"]})["state"], "success")
        self.assertIn("alpine/frr:latest", self.host.images)
        restarted = ImageService(self.manager, command=self.host.command)
        self.assertNotIn(entry["reference"], [item["image"] for item in restarted.catalog()])
        with TestClient(create_app(self.manager, "images-token", images=restarted)) as client:
            headers = {"Authorization": "Bearer images-token"}
            for path in ("/api/catalog", "/api/bootstrap"):
                body = client.get(path, headers=headers).json()
                cards = body["catalog"] if isinstance(body, dict) else body
                self.assertNotIn(entry["reference"], [item["image"] for item in cards])

    def test_preview_shows_only_registered_design_cards_and_real_catalog_requires_loaded_image(self):
        self.assertEqual(self.images.catalog(), [])
        self.manager.preview = True
        self.assertEqual(len(self.images.catalog()), 2)
        self.assertTrue(all(not item["present"] for item in self.images.catalog()))
        self.images.registry["images"] = []
        self.images.persist()
        self.assertEqual(ImageService(self.manager).catalog(), [])

    def test_firewall_card_uses_linux_adapter_and_topology_round_trips(self):
        job = self.job({"mode": "pull", "reference": "test/firewall:one", "template": "linux-firewall", "title": "测试防火墙"})
        self.assertEqual(job["state"], "success")
        card = next(item for item in self.images.catalog() if item["kind"] == "firewall")
        lab = example()
        lab["nodes"] = [{"id": "fw1", "name": "FW1", "kind": card["kind"], "template": card["template_id"],
                         "image": card["image"], "x": 0, "y": 0, "ports": [{"name": "eth0", "address": ""}],
                         "gateway": "", "command": [], "config": ""}]
        lab["links"] = []
        record = self.manager.save(lab)
        self.manager.deploy(record)
        self.assertEqual(self.manager.read(lab["id"])["topology"], lab)
        self.assertEqual(self.manager.terminal_target(lab["id"], "fw1")["argv"], ["sh", "-i"])
        self.assertFalse(card["capabilities"]["save_config"])
        self.manager.destroy(record)

    def test_build_uses_uploaded_context_and_selected_dockerfile(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("hello.txt", "hello")
            archive.writestr("Dockerfile", "ignored")
        upload = self.upload(output.getvalue(), "context")
        dockerfile = "FROM scratch\nCOPY hello.txt /hello.txt\n"
        job = self.job({"mode": "build", "reference": "test/build:one", "dockerfile": dockerfile, "upload": upload})
        self.assertEqual(job["state"], "success", job)
        self.assertEqual(self.host.last_context["Dockerfile"], dockerfile.encode())
        self.assertEqual(self.host.last_context["hello.txt"], b"hello")

    def test_download_url_loads_and_redacts_query_from_manifest(self):
        with patch.object(self.images, "download", side_effect=lambda job, url, path: path.write_bytes(b"archive")):
            job = self.job({"mode": "url", "url": "https://example.com/router.tar.xz?token=secret"})
        self.assertEqual(job["state"], "success", job)
        self.assertNotIn("secret", self.images.path.read_text())
        self.assertNotIn("secret", json.dumps(job))

    def test_failed_import_does_not_register_nonexistent_image(self):
        self.host.fail_image = True
        job = self.job({"mode": "pull", "reference": "test/fail:one"})
        self.assertEqual(job["state"], "error")
        self.assertNotIn("test/fail:one", [item["reference"] for item in self.images.snapshot()["images"]])
        self.assertFalse(self.manager.image_busy)

    def test_delete_updates_registry_only_after_docker_success(self):
        self.job({"mode": "pull", "reference": "test/delete:one"})
        item = next(item for item in self.images.snapshot()["images"] if item["reference"] == "test/delete:one")
        self.host.fail_image = True
        self.assertEqual(self.job({"mode": "delete", "id": item["id"]})["state"], "error")
        self.assertTrue(self.images.entry(item["id"])["present"])
        self.host.fail_image = False
        self.assertEqual(self.job({"mode": "delete", "id": item["id"]})["state"], "success")
        self.assertNotIn("test/delete:one", self.images.path.read_text())
        restarted = ImageService(self.manager, command=self.host.command)
        self.assertNotIn("test/delete:one", [item["reference"] for item in restarted.snapshot()["images"]])

    def test_saved_labs_and_external_containers_protect_images(self):
        del self.host.images["alpine/frr:latest"]
        self.job({"mode": "pull", "reference": "alpine/frr:latest"})
        self.images.sync()
        item = next(item for item in self.images.snapshot()["images"] if item["reference"] == "alpine/frr:latest")
        self.manager.save(example())
        job = self.job({"mode": "delete", "id": item["id"]})
        self.assertIn("实验引用", job["error"])
        self.manager.delete("first-lab")
        self.host.containers["foreign"] = {"Id": "foreign", "Name": "/foreign", "Image": item["image_id"], "Config": {"Image": item["reference"], "Labels": {}}}
        job = self.job({"mode": "delete", "id": item["id"]})
        self.assertIn("容器使用", job["error"])

    def test_jobs_and_deployment_are_serialized(self):
        entered, release = threading.Event(), threading.Event()
        def command(job_id, args):
            entered.set(); release.wait(10)
            return self.host.command(job_id, args)
        self.images.command = command
        self.images.start({"mode": "pull", "reference": "test/slow:one"})
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(LabError):
                self.images.start({"mode": "pull", "reference": "test/second:one"})
            self.manager.save(example())
            with self.assertRaisesRegex(LabError, "镜像任务"):
                self.manager.start_job("first-lab", "deploy")
        finally:
            release.set()

    def test_preview_rejects_mutations_but_can_read_inventory(self):
        self.manager.preview = True
        self.assertFalse(self.images.snapshot(refresh=True)["available"])
        with self.assertRaisesRegex(LabError, "设计模式"):
            self.images.start({"mode": "pull", "reference": "test/one"})

    def test_invalid_input_and_upload_limits(self):
        for value in ("file:///etc/passwd", "https://user:pass@example.com/image", "ftp://example.com/image"):
            with self.assertRaises(LabError): download_url(value)
        for value in ("--help", "alpine;id", "https://example.com/image"):
            with self.assertRaises(LabError): reference(value)
        with self.assertRaises(LabError):
            self.images.create_upload({"name": "image.tar", "size": 2 * 1024 * 1024, "kind": "archive"})
        with self.assertRaises(LabError): self.images.upload_path("../outside")

    def test_context_rejects_traversal_and_links(self):
        for name, type_ in (("../../outside", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            archive = Path(self.temp.name) / "context.tar"
            with tarfile.open(archive, "w") as target:
                item = tarfile.TarInfo(name); item.type = type_; item.linkname = "/etc/passwd"
                target.addfile(item, io.BytesIO())
            with self.assertRaises(LabError):
                extract_context(archive, Path(self.temp.name) / "extract")
        self.assertFalse((Path(self.temp.name).parent / "outside").exists())

    def test_local_adoption_and_forgetting_preserve_host_image_and_saved_lab(self):
        job = self.job({"mode": "local", "reference": "alpine/frr:latest", "template": "frr"})
        self.assertEqual(job["state"], "success", job)
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == "alpine/frr:latest")
        self.assertFalse(entry["can_delete"])
        self.assertEqual(entry["source"]["type"], "local")
        self.manager.save(example())
        saved_topology = self.manager.read("first-lab")["topology"]
        self.assertEqual(self.job({"mode": "delete", "id": entry["id"]})["state"], "error")
        self.assertEqual(self.job({"mode": "forget", "id": entry["id"]})["state"], "success")
        self.assertIn("alpine/frr:latest", self.host.images)
        self.assertEqual(self.manager.read("first-lab")["topology"], saved_topology)
        self.assertFalse(any(args[:2] == ["image", "rm"] for args, _ in self.host.calls))
        restarted = ImageService(self.manager, command=self.host.command)
        restarted.sync()
        self.assertNotIn("alpine/frr:latest", [item["reference"] for item in restarted.snapshot()["images"]])
        self.assertNotIn("alpine/frr:latest", [item["image"] for item in restarted.catalog()])
        self.assertEqual(self.job({"mode": "local", "reference": "nonexistent:latest"})["state"], "error")

    def test_legacy_discovery_migrates_without_granting_delete_permission(self):
        auto = self.images.new_entry("system/untouched:latest")
        explicit = self.images.new_entry("user/router:latest", {"template": "frr", "title": "手工绑定"})
        imported = self.images.new_entry("user/imported:latest", source={"type": "archive"})
        imported.pop("owned_image_id")
        for item in (auto, explicit, imported):
            self.host.images[item["reference"]] = "sha256:" + "e" * 64
        self.images.registry["images"].extend([auto, explicit, imported])
        self.images.persist()
        restarted = ImageService(self.manager, command=self.host.command)
        restarted.sync()
        entries = {item["reference"]: item for item in restarted.snapshot()["images"]}
        self.assertNotIn(auto["reference"], entries)
        self.assertEqual(entries[explicit["reference"]]["source"]["type"], "local")
        self.assertFalse(entries[explicit["reference"]]["can_delete"])
        self.assertFalse(entries[imported["reference"]]["can_delete"])
        self.assertIn(auto["reference"], self.host.images)
        self.assertNotIn(auto["reference"], restarted.path.read_text())

    def test_preexisting_image_import_does_not_grant_delete_permission(self):
        self.host.imports = ["system/existing:latest", "test/new:latest"]
        self.host.images["system/existing:latest"] = "sha256:" + "1" * 64
        upload = self.upload(b"archive")
        self.assertEqual(self.job({"mode": "archive", "upload": upload})["state"], "success")
        entries = {item["reference"]: item for item in self.images.snapshot()["images"]}
        self.assertFalse(entries["system/existing:latest"]["can_delete"])
        self.assertTrue(entries["test/new:latest"]["can_delete"])
        self.assertEqual(self.job({"mode": "delete", "id": entries["system/existing:latest"]["id"]})["state"], "error")
        self.assertEqual(self.job({"mode": "delete", "id": entries["test/new:latest"]["id"]})["state"], "success")
        self.assertIn("system/existing:latest", self.host.images)

    def test_unrelated_concurrent_images_and_aliases_are_not_registered(self):
        def command(job_id, args):
            result = self.host.command(job_id, args)
            self.host.images["system/concurrent:latest"] = "sha256:" + "f" * 64
            self.host.images["system/shared-alias:latest"] = self.host.images[self.host.imports[0]]
            return result
        self.images.command = command
        job = self.job({"mode": "archive", "upload": self.upload(b"archive")})
        self.assertEqual(job["state"], "success", job)
        self.assertEqual(set(job["images"]), set(self.host.imports))
        self.assertFalse(any(item["reference"].startswith("system/") for item in self.images.snapshot()["images"]))

    def test_delete_rechecks_external_replacement_and_revokes_ownership(self):
        self.job({"mode": "pull", "reference": "test/owned:latest"})
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == "test/owned:latest")
        self.assertTrue(entry["can_delete"])
        self.host.images[entry["reference"]] = "sha256:" + "f" * 64
        job = self.job({"mode": "delete", "id": entry["id"]})
        self.assertEqual(job["state"], "error")
        self.assertIn("只能移出管理清单", job["error"])
        self.assertFalse(self.images.snapshot()["images"][-1]["can_delete"])
        self.assertEqual(self.host.images[entry["reference"]], "sha256:" + "f" * 64)
        self.assertFalse(any(args[:2] == ["image", "rm"] for args, _ in self.host.calls))
        # Returning the tag to its old ID must not silently restore ownership.
        self.host.images[entry["reference"]] = entry["image_id"]
        self.images.sync()
        self.assertFalse(self.images.can_delete(self.images.entry(entry["id"])))

    def test_owned_image_can_be_updated_and_forgotten_without_deletion(self):
        ref = "test/owned:latest"
        self.job({"mode": "pull", "reference": ref})
        def command(job_id, args):
            result = self.host.command(job_id, args)
            self.host.images[ref] = "sha256:" + "e" * 64
            return result
        self.images.command = command
        self.assertEqual(self.job({"mode": "pull", "reference": ref})["state"], "success")
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == ref)
        self.assertTrue(entry["can_delete"])
        self.assertEqual(self.job({"mode": "forget", "id": entry["id"]})["state"], "success")
        self.assertIn(ref, self.host.images)
        self.assertNotIn(ref, [item["reference"] for item in self.images.snapshot(refresh=True)["images"]])

    def test_http_cannot_delete_hidden_or_protected_host_images(self):
        hidden = self.images.new_entry("system/hidden:latest")
        self.images.registry["images"].append(hidden)
        self.host.images[hidden["reference"]] = "sha256:" + "f" * 64
        with TestClient(create_app(self.manager, "images-token", images=self.images)) as client:
            headers = {"Authorization": "Bearer images-token"}
            data = client.post("/api/images/refresh", json={}, headers=headers).json()
            self.assertNotIn(hidden["reference"], [item["reference"] for item in data["images"]])
            self.assertEqual(client.delete("/api/images/" + hidden["id"], headers=headers).status_code, 400)
            protected = data["images"][0]
            result = client.delete("/api/images/" + protected["id"], headers=headers)
            self.assertEqual(result.status_code, 202)
            self.images.wait()
            self.assertEqual(self.images.jobs[result.json()["id"]]["state"], "error")
            self.assertIn(protected["reference"], self.host.images)
        self.assertFalse(any(args[:2] == ["image", "rm"] for args, _ in self.host.calls))

    def test_http_upload_auth_size_failure_and_task(self):
        with TestClient(create_app(self.manager, "images-token", images=self.images)) as client:
            headers = {"Authorization": "Bearer images-token"}
            url = "/api/images/uploads"
            self.assertEqual(client.post(url, json={}).status_code, 401)
            self.assertEqual(client.post(url, json={}, headers={**headers, "Origin": "http://foreign.invalid"}).status_code, 403)
            info = client.post(url, json={"name": "test.tar", "size": 4, "kind": "archive"}, headers=headers).json()
            endpoint = url + "/" + info["id"]
            binary = {**headers, "Content-Type": "application/octet-stream"}
            self.assertEqual(client.put(endpoint, content=b"too long", headers=binary).status_code, 400)
            self.assertFalse(self.images.upload_path(info["id"]).exists())
            info = client.post(url, json={"name": "test.tar", "size": 4, "kind": "archive"}, headers=headers).json()
            self.assertEqual(client.put(url + "/" + info["id"], content=b"data", headers=binary).status_code, 200)
            result = client.post("/api/images/jobs", json={"mode": "archive", "upload": info["id"]}, headers=headers)
            self.assertEqual(result.status_code, 202)
            self.images.wait()
            self.assertEqual(client.get("/api/images", headers=headers).json()["jobs"][0]["state"], "success")


if __name__ == "__main__":
    unittest.main()
