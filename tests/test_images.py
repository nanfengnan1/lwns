"""Image inventory, import jobs, streaming uploads and deletion consistency."""
import io
import json
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

    def upload(self, content, kind="archive"):
        info = self.images.create_upload({"name": "archive.tar.xz", "size": len(content), "kind": kind})
        self.images.begin_upload(info["id"])
        (self.images.upload_path(info["id"]) / "data").write_bytes(content)
        self.images.finish_upload(info["id"], len(content))
        return info["id"]

    def test_default_file_and_external_inventory_sync(self):
        self.assertTrue(self.images.path.is_file())
        self.assertEqual(self.manager.list_labs(), [])
        self.host.images["external/device:latest"] = "sha256:" + "e" * 64
        self.images.sync()
        entry = next(item for item in self.images.snapshot()["images"] if item["reference"] == "external/device:latest")
        self.assertEqual(entry["source"]["type"], "discovered")
        del self.host.images["external/device:latest"]
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
        self.assertEqual(self.job({"mode": "delete", "id": entry["id"]})["state"], "success")
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
