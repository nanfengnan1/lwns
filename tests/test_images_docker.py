"""Opt-in real Docker image lifecycle, isolated tags and temporary registry only."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from urllib.request import urlopen
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from fastapi.testclient import TestClient
from lab_core import LabManager
from lab_images import ImageService
from lab_server import create_app


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ImageDockerFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="route-ovs-images-", dir=os.environ.get("ROUTE_OVS_TEST_DIR"))
        self.root = Path(self.temp.name)
        self.prefix = "rov-img-" + uuid.uuid4().hex[:12]
        self.manager = LabManager(self.root / "data")
        self.images = ImageService(self.manager)
        self.registry = None
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietFiles, directory=str(self.root)))
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.headers = {"Authorization": "Bearer image-browser-check"}
        self.app = create_app(self.manager, "image-browser-check", images=self.images)

    def prepare_archive(self):
        build = self.root / "seed"
        build.mkdir()
        (build / "marker").write_text(self.prefix, encoding="utf-8")
        (build / "Dockerfile").write_text(f'FROM scratch\nLABEL io.route-ovs.image-test="{self.prefix}"\nCOPY marker /marker\n', encoding="utf-8")
        ref = self.prefix + ":archive"
        self.manager.dock("build", "--network", "none", "-t", ref, str(build), timeout=120)
        archive = self.root / "image.tar"
        self.manager.dock("image", "save", "--output", str(archive), ref, timeout=120)
        self.archive = archive
        self.manager.dock("image", "rm", ref)
        return {"prefix": self.prefix, "archive": str(self.archive), "url": f"http://127.0.0.1:{self.http.server_port}/image.tar", "data_dir": str(self.manager.directory)}

    def submit(self, client, payload):
        response = client.post("/api/images/jobs", json=payload, headers=self.headers)
        if response.status_code != 202:
            raise AssertionError(response.text)
        self.images.wait()
        result = self.images.jobs[response.json()["id"]]
        if result["state"] != "success":
            raise AssertionError(result)
        return result

    def upload(self, client, name, value, kind):
        response = client.post("/api/images/uploads", json={"name": name, "size": len(value), "kind": kind}, headers=self.headers)
        if response.status_code != 201:
            raise AssertionError(response.text)
        upload = response.json()["id"]
        response = client.put("/api/images/uploads/" + upload, content=value, headers={**self.headers, "Content-Type": "application/octet-stream"})
        if response.status_code != 200:
            raise AssertionError(response.text)
        return upload

    def delete(self, client, ref):
        item = next(item for item in self.images.snapshot()["images"] if item["reference"] == ref)
        response = client.delete("/api/images/" + item["id"], headers=self.headers)
        if response.status_code != 202:
            raise AssertionError(response.text)
        self.images.wait()
        result = self.images.jobs[response.json()["id"]]
        if result["state"] != "success":
            raise AssertionError(result)

    def cleanup(self):
        self.images.wait()
        self.http.shutdown(); self.http.server_close()
        if self.registry:
            self.manager.dock("rm", "-f", "-v", self.registry)
        refs = self.manager.dock("image", "ls", "--filter", "label=io.route-ovs.image-test=" + self.prefix,
                                 "--format", "{{.Repository}}:{{.Tag}}|{{.ID}}", timeout=30).splitlines()
        for line in refs:
            ref, image_id = line.split("|", 1)
            self.manager.dock("image", "rm", image_id if "<none>" in ref else ref, check=False)
        self.temp.cleanup()


@unittest.skipUnless(os.environ.get("ROUTE_OVS_IMAGE_DOCKER_TESTS") == "1", "opt-in real image lifecycle test")
class ImageDockerTests(unittest.TestCase):
    def test_existing_local_image_cannot_be_deleted_through_manager(self):
        fixture = ImageDockerFixture()
        self.addCleanup(fixture.cleanup)
        fixture.prepare_archive()
        ref = fixture.prefix + ":archive"
        fixture.manager.dock("load", "--input", str(fixture.archive), timeout=120)
        with TestClient(fixture.app) as client:
            snapshot = client.post("/api/images/refresh", json={}, headers=fixture.headers).json()
            self.assertNotIn(ref, [item["reference"] for item in snapshot["images"]])
            fixture.submit(client, {"mode": "local", "reference": ref})
            item = next(item for item in fixture.images.snapshot()["images"] if item["reference"] == ref)
            self.assertFalse(item["can_delete"])
            response = client.delete("/api/images/" + item["id"], headers=fixture.headers)
            self.assertEqual(response.status_code, 202)
            fixture.images.wait()
            self.assertEqual(fixture.images.jobs[response.json()["id"]]["state"], "error")
            fixture.submit(client, {"mode": "forget", "id": item["id"]})
            self.assertTrue(json.loads(fixture.manager.dock("image", "inspect", ref)))
            self.assertNotIn(ref, [item["reference"] for item in fixture.images.snapshot(refresh=True)["images"]])

    def test_tar_upload_and_url_load_directly(self):
        fixture = ImageDockerFixture()
        self.addCleanup(fixture.cleanup)
        assets = fixture.prepare_archive()
        expected = fixture.archive.read_bytes()
        loaded_paths = []
        original_command = fixture.images.command
        def command(job_id, args):
            if args[0] == "load":
                path = Path(args[-1])
                self.assertIn(path.name, ("data", "image-archive"))
                self.assertEqual(path.read_bytes(), expected)
                loaded_paths.append(path)
            return original_command(job_id, args)
        fixture.images.command = command
        with TestClient(fixture.app) as client:
            upload = fixture.upload(client, "image.tar", fixture.archive.read_bytes(), "archive")
            payloads = [{"mode": "archive", "upload": upload}, {"mode": "url", "url": assets["url"]}]
            ref = fixture.prefix + ":archive"
            for payload in payloads:
                with self.subTest(mode=payload["mode"]):
                    job = fixture.submit(client, payload)
                    self.assertNotIn("解压", job["logs"])
                    self.assertIn(ref, job["images"])
                    self.assertEqual(json.loads(fixture.manager.dock("image", "inspect", ref))[0]["Config"]["Labels"]
                                     ["io.route-ovs.image-test"], fixture.prefix)
                    self.assertFalse(loaded_paths[-1].parent.exists())
                    fixture.delete(client, ref)
        self.assertEqual(len(loaded_paths), 2)
        self.assertFalse(fixture.images.upload_path(upload).exists())

    def test_build_archive_url_pull_delete_and_persistence(self):
        fixture = ImageDockerFixture()
        self.addCleanup(fixture.cleanup)
        assets = fixture.prepare_archive()
        with TestClient(fixture.app) as client:
            # Real Dockerfile build with a COPY file supplied via the upload API.
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode="w:gz") as archive:
                value = b"context copy works"
                item = tarfile.TarInfo("message.txt"); item.size = len(value)
                archive.addfile(item, io.BytesIO(value))
            upload = fixture.upload(client, "context.tar.gz", content.getvalue(), "context")
            build_ref = fixture.prefix + ":build"
            fixture.submit(client, {"mode": "build", "reference": build_ref, "upload": upload,
                                    "dockerfile": f'FROM scratch\nLABEL io.route-ovs.image-test="{fixture.prefix}"\nCOPY message.txt /message.txt\n'})
            archive_ref = fixture.prefix + ":archive"
            upload = fixture.upload(client, "image.tar", fixture.archive.read_bytes(), "archive")
            fixture.submit(client, {"mode": "archive", "upload": upload, "template": "linux-host", "title": "归档测试镜像"})
            self.assertTrue(any(item["image"] == archive_ref for item in fixture.images.catalog()))
            fixture.delete(client, archive_ref)
            self.assertFalse(any(item["reference"] == archive_ref for item in fixture.images.snapshot()["images"]))
            fixture.submit(client, {"mode": "url", "url": assets["url"]})
            # Use an isolated local registry, never push to an external service.
            fixture.registry = fixture.manager.dock("run", "-d", "--pull", "never", "--name", fixture.prefix + "-registry",
                "--label", "io.route-ovs.image-test=" + fixture.prefix, "-p", "127.0.0.1::5000", "registry:2")
            port = fixture.manager.dock("port", fixture.registry, "5000/tcp").rsplit(":", 1)[-1]
            registry_url = "http://127.0.0.1:" + port + "/v2/"
            for attempt in range(30):
                try:
                    with urlopen(registry_url, timeout=2) as response:
                        self.assertEqual(response.status, 200)
                    break
                except OSError:
                    if attempt == 29: raise
                    time.sleep(0.2)
            pull_ref = f"127.0.0.1:{port}/{fixture.prefix}:pulled"
            fixture.manager.dock("image", "tag", build_ref, pull_ref)
            fixture.manager.dock("push", pull_ref, timeout=120)
            fixture.manager.dock("image", "rm", pull_ref)
            fixture.submit(client, {"mode": "pull", "reference": pull_ref})
            self.assertTrue(any(item["reference"] == pull_ref and item["present"] for item in fixture.images.snapshot()["images"]))
            for ref in (archive_ref, build_ref, pull_ref):
                fixture.delete(client, ref)
            restarted = ImageService(fixture.manager)
            self.assertFalse(any(fixture.prefix in item["reference"] for item in restarted.snapshot()["images"]))


if __name__ == "__main__":
    unittest.main()
