"""Device package HTTP workflows, publication boundaries and shared job locks."""
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_images import ImageHost
from test_lab import LabManager, LabError
from lab_device_packages import inspect_package, pack_device
from lab_device_service import DevicePackageService
from lab_images import ImageService
from lab_server import create_app


def descriptor():
    return {"schema_version": 1, "id": "test-host", "version": "1.0.0", "name": "测试主机",
            "category": "host", "image": "alpine/vpcs:latest", "source": {"type": "repository"},
            "console": ["sh", "-i"],
            "persistent_dirs": [{"id": "config", "target": "/etc/lab", "initialize_from": "empty"}],
            "startup": {"phase": "after_links", "service": {"exec": ["sleep", "infinity"]},
                        "ready": {"exec": ["test", "-d", "/etc/lab"]},
                        "config_files": ["/etc/lab/startup.conf"]},
            "actions": {"save_config": {"exec": ["/usr/local/bin/save-config"]}}}


class PackageHost(ImageHost):
    def __call__(self, argv, **kwargs):
        args = argv[3:]
        if argv[0] == "docker" and args[:2] == ["image", "inspect"]:
            self.calls.append((argv, kwargs))
            ref = args[-1]
            image_id = self.images.get(ref) or (ref if ref in self.images.values() else None)
            if image_id is None:
                raise LabError("No such image")
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Id": image_id, "Os": "linux", "Architecture": "amd64"}]), "")
        return super().__call__(argv, **kwargs)


class DevicePackageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = PackageHost()
        self.manager = LabManager(Path(self.temp.name) / "data", runner=self.host)
        self.manager.authorize = lambda: None
        self.images = ImageService(self.manager, command=self.host.command, max_upload=1024 * 1024)
        self.packages = DevicePackageService(self.manager, self.images, command=self.host.command, max_upload=1024 * 1024)
        self.app = create_app(self.manager, "secret", images=self.images, device_packages=self.packages)
        self.headers = {"Authorization": "Bearer secret", "Origin": "http://testserver"}

    def tearDown(self):
        self.packages.wait()
        self.images.wait()
        self.temp.cleanup()

    def package(self, value=None):
        path = Path(self.temp.name) / ("input-" + str(len(list(Path(self.temp.name).glob("*.lwns")))) + ".lwns")
        pack_device(value or descriptor(), path)
        return path

    def upload(self, client, path):
        content = path.read_bytes()
        created = client.post("/api/device-packages/uploads", headers=self.headers,
                              json={"name": path.name, "size": len(content), "kind": "package"})
        self.assertEqual(created.status_code, 201, created.text)
        upload_id = created.json()["id"]
        response = client.put("/api/device-packages/uploads/" + upload_id,
                              headers={**self.headers, "Content-Type": "application/octet-stream"}, content=content)
        self.assertEqual(response.status_code, 200, response.text)
        return upload_id

    def start(self, client, payload):
        response = client.post("/api/device-packages/jobs", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 202, response.text)
        self.packages.wait()
        return self.packages.jobs[response.json()["id"]]

    def test_pack_download_inspect_and_import_then_rename(self):
        with TestClient(self.app) as client:
            job = self.start(client, {"mode": "pack", "descriptor": descriptor(), "name": "设备包名称",
                                      "source": {"type": "repository", "reference": "alpine/vpcs:latest"}})
            self.assertEqual(job["state"], "success", job)
            self.assertEqual(self.packages.library.entries(), [], "Packing must not register a device")
            url = job["result"]["download_url"]
            self.assertEqual(client.get(url).status_code, 401)
            download = client.get(url, headers=self.headers)
            self.assertEqual(download.status_code, 200)
            self.assertIn(".lwns", download.headers["content-disposition"])
            path = Path(self.temp.name) / "web-made.lwns"
            path.write_bytes(download.content)
            self.assertEqual(inspect_package(path)["descriptor"]["name"], "设备包名称")
            upload_id = self.upload(client, path)
            inspected = client.post("/api/device-packages/inspect", headers=self.headers, json={"upload_id": upload_id})
            self.assertEqual(inspected.status_code, 200, inspected.text)
            self.assertEqual(self.packages.library.entries(), [])
            imported = self.start(client, {"mode": "import", "upload_id": upload_id, "name": "我的设备"})
            self.assertEqual(imported["state"], "success", imported)
            entry = imported["result"]["device"]
            self.assertEqual(entry["name"], "我的设备")
            self.assertEqual(entry["image_id"], self.host.images["alpine/vpcs:latest"])
            cards = client.get("/api/catalog", headers=self.headers).json()
            self.assertTrue(any(card["id"] == entry["id"] for card in cards), cards)
            renamed = client.patch("/api/device-packages/" + entry["id"], headers=self.headers, json={"name": "重新命名"})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual(renamed.json()["id"], entry["id"])
            self.assertEqual(inspect_package(self.packages.library.package_path(entry["id"]))["descriptor"]["name"], "设备包名称")

    def test_origin_auth_size_and_inspection_never_execute_device_commands(self):
        with TestClient(self.app) as client:
            url = "/api/device-packages/uploads"
            payload = {"name": "x.lwns", "kind": "package", "size": 10}
            self.assertEqual(client.post(url, json=payload).status_code, 401)
            foreign = {**self.headers, "Origin": "https://foreign.example"}
            self.assertEqual(client.post(url, headers=foreign, json=payload).status_code, 403)
            for bad in ({**payload, "name": "x.tar"}, {**payload, "size": 2 * 1024 * 1024}, {**payload, "name": "../x.lwns"}):
                self.assertEqual(client.post(url, headers=self.headers, json=bad).status_code, 400)
            upload_id = self.upload(client, self.package())
            before = copy.deepcopy(self.host.calls)
            result = client.post("/api/device-packages/inspect", headers=self.headers, json={"upload_id": upload_id})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.host.calls, before)
            self.assertEqual(self.packages.library.entries(), [])
            self.assertEqual(client.patch("/api/device-packages/missing", headers=foreign, json={"name": "X"}).status_code, 403)

    def test_failed_import_can_retry_without_creating_a_library_card(self):
        desc = descriptor()
        desc["image"] = "test/missing:latest"
        with TestClient(self.app) as client:
            upload_id = self.upload(client, self.package(desc))
            self.host.fail_image = True
            failed = self.start(client, {"mode": "import", "upload_id": upload_id})
            self.assertEqual(failed["state"], "error", failed)
            self.assertEqual(self.packages.library.entries(), [])
            self.assertFalse(self.manager.image_busy)
            self.assertEqual(self.packages.upload_info(upload_id)["state"], "ready")
            self.host.fail_image = False
            retried = self.start(client, {"mode": "import", "upload_id": upload_id})
            self.assertEqual(retried["state"], "success", retried)
            self.assertEqual(len(self.packages.library.entries()), 1)

    def test_shared_lock_prevents_image_and_package_jobs_overlapping(self):
        self.manager.image_busy = True
        with self.assertRaisesRegex(LabError, "任务"):
            self.images.start({"mode": "local", "reference": "alpine/vpcs:latest"})
        with self.assertRaisesRegex(LabError, "任务"):
            self.packages.start({"mode": "pack", "descriptor": descriptor(), "source": {"type": "repository"}})
        self.assertEqual(self.packages.jobs, {})
        self.manager.image_busy = False

    def test_referenced_definition_cannot_be_deleted_or_its_image_removed(self):
        entry = self.packages.import_file(self.package())
        self.manager.save({"version": 1, "id": "test-project", "name": "引用设备的项目", "links": [], "nodes": [
            {"id": "node1", "name": "PC1", "kind": "host", "template": entry["id"], "image": entry["image_id"],
             "ports": [{"name": "eth0", "address": ""}], "x": 0, "y": 0, "gateway": "", "command": [], "config": ""}]})
        with self.assertRaises(LabError):
            self.packages.remove(entry["id"])
        with self.assertRaisesRegex(LabError, "设备库"):
            self.images.ensure_unused(entry["image"], entry["image_id"])
        self.manager.delete("test-project")
        before = dict(self.host.images)
        self.packages.remove(entry["id"])
        self.assertEqual(self.packages.library.entries(), [])
        self.assertEqual(self.host.images, before)

    def test_same_version_conflict_precedes_docker_mutations(self):
        entry = self.packages.import_file(self.package())
        changed = descriptor()
        changed["console"] = ["bash"]
        with TestClient(self.app) as client:
            upload_id = self.upload(client, self.package(changed))
            with patch.object(self.packages, "prepare_image", side_effect=AssertionError("must not prepare conflicting image")):
                job = self.start(client, {"mode": "import", "upload_id": upload_id})
            self.assertEqual(job["state"], "error", job)
            self.assertIn("版本", job["error"])
        self.assertEqual(self.packages.library.entries()[0]["package_sha256"], entry["package_sha256"])

    def test_recipe_making_does_not_build_and_survives_service_restart(self):
        self.manager.preview = True
        with TestClient(self.app) as client:
            job = self.start(client, {"mode": "pack", "descriptor": descriptor(),
                                      "source": {"type": "dockerfile", "dockerfile": "FROM alpine:3.23\n"}})
            self.assertEqual(job["state"], "success", job)
            self.assertFalse(any(args and args[0] == "build" for args, _ in self.host.calls))
        restarted = DevicePackageService(self.manager, self.images, command=self.host.command)
        path, filename = restarted.artifact(job["id"])
        self.assertTrue(path.is_file())
        self.assertEqual(inspect_package(path)["descriptor"]["source"]["type"], "dockerfile")
        self.assertTrue(filename.endswith(".lwns"))

    def test_cli_import_helper_releases_uploads_on_success_and_failure(self):
        path = self.package()
        for _ in range(10):
            self.packages.import_file(path)
            self.assertEqual(list(self.packages.uploads.iterdir()), [])
        changed = descriptor()
        changed["console"] = ["bash"]
        with self.assertRaises(LabError):
            self.packages.import_file(self.package(changed))
        self.assertEqual(list(self.packages.uploads.iterdir()), [])
        with patch("lab_device_service.shutil.copyfile", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                self.packages.import_file(path)
        self.assertEqual(list(self.packages.uploads.iterdir()), [])

    def test_legacy_upload_and_old_completed_artifact_survive_upgrade(self):
        path = self.package()
        legacy = path.with_suffix(".rov")
        path.replace(legacy)
        with TestClient(self.app) as client:
            upload_id = self.upload(client, legacy)
            job = self.start(client, {"mode": "import", "upload_id": upload_id})
            self.assertEqual(job["state"], "success", job)
            job = self.start(client, {"mode": "pack", "descriptor": descriptor(),
                                      "source": {"type": "repository", "reference": "test/router:one"}})
            self.assertEqual(job["state"], "success", job)
        path, filename = self.packages.artifact(job["id"])
        old_path = path.with_suffix(".rov")
        path.rename(old_path)
        restored = DevicePackageService(self.manager, self.images, command=self.host.command)
        self.assertEqual(restored.artifact(job["id"])[0], old_path)

    def test_web_import_success_and_failed_maker_release_upload_slots(self):
        path = self.package()
        with TestClient(self.app) as client:
            for _ in range(10):
                upload_id = self.upload(client, path)
                job = self.start(client, {"mode": "import", "upload_id": upload_id})
                self.assertEqual(job["state"], "success", job)
                self.assertFalse(self.packages.upload_path(upload_id).exists())
        info = self.packages.create_upload({"name": "bad.tar", "size": 7, "kind": "archive"})
        self.packages.begin_upload(info["id"])
        (self.packages.upload_path(info["id"]) / "data").write_bytes(b"invalid")
        self.packages.finish_upload(info["id"], 7)
        job = self.packages.start({"mode": "pack", "descriptor": descriptor(),
                                   "source": {"type": "archive", "upload_id": info["id"]}})
        self.packages.wait()
        self.assertEqual(self.packages.jobs[job["id"]]["state"], "error")
        self.assertFalse(self.packages.upload_path(info["id"]).exists())


if __name__ == "__main__":
    unittest.main()
