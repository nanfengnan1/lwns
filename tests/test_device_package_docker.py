"""Opt-in .rov image preparation using an existing base and isolated tags only.

LWNS_DEVICE_PACKAGE_DOCKER_TESTS=1 .venv/bin/python -m unittest discover -s tests -p test_device_package_docker.py -v
No containers or networks are created; the existing base tag is never changed.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_core import LabError, LabManager
from lab_device_packages import DeviceLibrary, inspect_package
from lab_device_service import DevicePackageService
from test_device_packages import descriptor


@unittest.skipUnless(os.environ.get("LWNS_DEVICE_PACKAGE_DOCKER_TESTS") == "1",
                     "opt-in real .rov image export/load/build test")
class DevicePackageDockerTests(unittest.TestCase):
    def test_local_export_offline_import_recipe_build_and_cli_import(self):
        with tempfile.TemporaryDirectory(prefix="lwns-package-docker-", dir=os.environ.get("LWNS_TEST_DIR")) as directory:
            root = Path(directory)
            manager = LabManager(root / "data")
            service = DevicePackageService(manager)
            try:
                base = service.image_info("alpine/vpcs:latest")
            except LabError as exc:
                self.skipTest("required pre-existing local alpine/vpcs:latest unavailable: " + str(exc))
            base_id = base["Id"]
            initial_containers = set(manager.dock("ps", "-aq").split())
            token = uuid.uuid4().hex
            archive_ref = "lwns-package-test:" + token + "-archive"
            recipe_ref = "lwns-package-test:" + token + "-recipe"
            owned = []

            def require_missing(reference):
                try:
                    service.image_info(reference)
                except LabError:
                    return
                self.fail("Refusing to overwrite an existing test tag: " + reference)

            def submit(payload):
                job = service.start(payload)
                service.wait()
                completed = service.jobs[job["id"]]
                self.assertEqual(completed["state"], "success", completed)
                return completed

            try:
                require_missing(archive_ref)
                manager.dock("image", "tag", base_id, archive_ref)
                owned.append(archive_ref)
                definition = descriptor(id="package-" + token, category="host", image=archive_ref,
                                        name="Isolated package integration test")
                exported = submit({"mode": "pack", "descriptor": definition,
                                   "source": {"type": "local", "reference": archive_ref}})
                archive_package, _ = service.artifact(exported["id"])
                report = inspect_package(archive_package)
                self.assertEqual(report["descriptor"]["source"], {"type": "archive", "path": "image.tar"})
                self.assertIn("image.tar", report["resources"])
                self.assertEqual(service.library.entries(), [], "Making must not install a device")
                self.assertIn("$ docker save", exported["logs"])

                # Remove only our alias, leaving the pre-existing base intact.
                manager.dock("image", "rm", archive_ref)
                require_missing(archive_ref)
                self.assertEqual(service.image_info("alpine/vpcs:latest")["Id"], base_id)
                imported = service.import_file(archive_package, name="Offline imported device")
                self.assertEqual(imported["image_id"], base_id)
                self.assertEqual(service.image_info(archive_ref)["Id"], base_id)
                imported_job = next(job for job in service.jobs.values() if job["mode"] == "import")
                self.assertIn("$ docker load", imported_job["logs"])
                self.assertEqual(service.library.resolve(imported["id"])["image"], base_id)
                self.assertEqual(list(service.uploads.iterdir()), [], "Synchronous imports must release upload staging")

                # FROM only uses the already available base, with no RUN or fetch.
                require_missing(recipe_ref)
                recipe_definition = copy.deepcopy(definition)
                recipe_definition.update(id="recipe-" + token, image=recipe_ref)
                recipe = submit({"mode": "pack", "descriptor": recipe_definition,
                                 "source": {"type": "dockerfile", "reference": recipe_ref,
                                            "dockerfile": "FROM alpine/vpcs:latest\n"}})
                recipe_package, _ = service.artifact(recipe["id"])
                self.assertEqual(inspect_package(recipe_package)["descriptor"]["source"]["type"], "dockerfile")
                require_missing(recipe_ref)
                owned.append(recipe_ref)
                built = service.import_file(recipe_package)
                self.assertEqual(built["image_id"], base_id)
                self.assertTrue(any("$ docker build" in job["logs"] for job in service.jobs.values()))

                # Invoke the real CLI entrypoint against another isolated data root.
                cli_data = root / "cli-data"
                server = Path(__file__).resolve().parents[1] / "script/python/lab_server.py"
                cli = subprocess.run([sys.executable, str(server), "device", "import", str(archive_package),
                                      "--data-dir", str(cli_data), "--name", "CLI imported device"],
                                     text=True, encoding="utf-8", capture_output=True, timeout=180, check=False)
                self.assertEqual(cli.returncode, 0, cli.stderr)
                cli_entry = json.loads(cli.stdout)
                self.assertEqual(cli_entry["name"], "CLI imported device")
                self.assertEqual(cli_entry["image_id"], base_id)
                self.assertEqual(DeviceLibrary(cli_data).resolve(cli_entry["id"])["image"], base_id)
                self.assertEqual(list((cli_data / "device-packages/uploads").iterdir()), [])
            finally:
                service.wait()
                service.images.wait()
                for reference in reversed(owned):
                    try:
                        actual = service.image_info(reference)["Id"]
                    except LabError:
                        continue
                    self.assertEqual(actual, base_id, "Unexpected tag content: refusing cleanup")
                    manager.dock("image", "rm", reference)
                self.assertEqual(service.image_info("alpine/vpcs:latest")["Id"], base_id)
                self.assertTrue(initial_containers.issubset(set(manager.dock("ps", "-aq").split())),
                                "Pre-existing containers must remain")


if __name__ == "__main__":
    unittest.main()
