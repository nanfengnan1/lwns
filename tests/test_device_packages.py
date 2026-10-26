"""Portable device definitions, immutable versions and CLI packaging boundaries."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from lab_errors import LabError
from lab_device_schema import json_object, template_id, validate_descriptor
from lab_device_packages import DeviceLibrary, canonical_json, extract_package, inspect_package, pack_device
from lab_device_cli import library_lock, main


def descriptor(**changes):
    result = {
        "schema_version": 1, "id": "test-router", "version": "1.0.0", "name": "测试路由器",
        "category": "router", "profile": "generic", "image": "test/router:one",
        "source": {"type": "repository"}, "console": ["sh", "-i"],
        "persistent_dirs": [{"id": "config", "target": "/etc/test", "initialize_from": "image", "owner": "100:101"}],
        "startup": {"phase": "after_links", "service": {"exec": ["/usr/local/bin/start-device"]},
                    "config_files": ["/etc/test/startup.conf"], "ready": {"exec": ["/usr/local/bin/ready"]}},
        "actions": {"save_config": {"exec": ["/usr/local/bin/save-config"]}},
    }
    result.update(changes)
    return result


def docker_archive(path, reference="test/router:one"):
    with tarfile.open(path, "w") as archive:
        for name, body in {
            "manifest.json": json.dumps([{"Config": "config.json", "RepoTags": [reference], "Layers": []}]).encode(),
            "config.json": b'{"architecture":"amd64","os":"linux"}',
        }.items():
            item = tarfile.TarInfo(name)
            item.size = len(body)
            archive.addfile(item, io.BytesIO(body))
    return path


class DescriptorTests(unittest.TestCase):
    def test_canonical_defaults_and_copy(self):
        raw = descriptor()
        result = validate_descriptor(raw)
        self.assertEqual(result["actions"]["save_config"]["expected_files"], ["/etc/test/startup.conf"])
        self.assertEqual(result["persistent_dirs"][0]["permissions"], "0750")
        self.assertEqual(result["startup"]["ready"]["interval_seconds"], 0.5)
        self.assertNotIn("expected_files", raw["actions"]["save_config"])
        self.assertEqual(validate_descriptor(result), result)

    def test_category_does_not_select_frr(self):
        self.assertEqual(validate_descriptor(descriptor())["profile"], "generic")

    def test_runtime_capabilities_are_explicit_and_restricted(self):
        raw = descriptor(runtime={"cap_add": ["SYS_ADMIN"]})
        self.assertEqual(validate_descriptor(raw)["runtime"], {"cap_add": ["SYS_ADMIN"]})
        for runtime in ({"privileged": True}, {"network": "host"}, {"cap_add": ["ALL"]},
                        {"cap_add": ["SYS_PTRACE"]}, {"cap_add": "SYS_ADMIN"},
                        {"cap_add": ["SYS_ADMIN", "SYS_ADMIN"]}, {"cap_add": [{}]}):
            with self.subTest(runtime=runtime), self.assertRaises(LabError):
                validate_descriptor(descriptor(runtime=runtime))

    def test_required_save_ready_and_output(self):
        raw = descriptor()
        raw["actions"] = {}
        with self.assertRaisesRegex(LabError, "save_config"):
            validate_descriptor(raw)
        raw = descriptor()
        del raw["startup"]["ready"]
        with self.assertRaisesRegex(LabError, "startup.ready"):
            validate_descriptor(raw)
        raw = descriptor()
        raw["startup"]["config_files"] = []
        with self.assertRaisesRegex(LabError, "expected_files"):
            validate_descriptor(raw)

    def test_unknown_fields_are_rejected(self):
        for raw in (descriptor(ports=4), descriptor(adapter="frr"), descriptor(schema_version=True)):
            with self.subTest(raw=raw), self.assertRaises(LabError):
                validate_descriptor(raw)

    def test_mount_paths_and_saved_output_cannot_escape(self):
        for target in ("/", "/etc/../root", "/proc", "/sys/a", "/run", "/run/route-ovs", "/run/route-ovs-state/config", "/etc/test/", "/etc/test,readonly"):
            raw = descriptor()
            raw["persistent_dirs"][0]["target"] = target
            with self.subTest(target=target), self.assertRaises(LabError):
                validate_descriptor(raw)
        raw = descriptor()
        raw["actions"]["save_config"]["expected_files"] = ["/etc/password"]
        with self.assertRaisesRegex(LabError, "持久化目录"):
            validate_descriptor(raw)
        raw = descriptor()
        raw["startup"]["ready"]["expected_files"] = ["/outside/mount"]
        with self.assertRaisesRegex(LabError, "持久化目录"):
            validate_descriptor(raw)

    def test_duplicate_mounts_reserved_ids_and_shell_strings_rejected(self):
        raw = descriptor()
        raw["persistent_dirs"].append({"id": "nested", "target": "/etc/test/other"})
        with self.assertRaisesRegex(LabError, "嵌套"):
            validate_descriptor(raw)
        raw = descriptor()
        raw["persistent_dirs"][0]["id"] = "backups"
        with self.assertRaises(LabError):
            validate_descriptor(raw)
        raw = descriptor()
        raw["actions"]["save_config"]["exec"] = "echo test"
        with self.assertRaisesRegex(LabError, "参数数组"):
            validate_descriptor(raw)

    def test_versions_paths_and_duplicate_json(self):
        for version in ("1.0", "1.0-rc.1", "1.0.0", "1.0.0+build.1"):
            with self.subTest(version=version):
                self.assertEqual(validate_descriptor(descriptor(version=version))["version"], version)
        for version in ("../1.0.0", "latest", "1", "1/0/0", "1.0.", "1..0", "1.0.0.0"):
            with self.subTest(version=version), self.assertRaises(LabError):
                validate_descriptor(descriptor(version=version))
        with self.assertRaisesRegex(LabError, "重复"):
            json_object('{"id":"one","id":"two"}')
        with self.assertRaises(LabError):
            json_object('{"bad":NaN}')

    def test_source_path_and_frr_profile_contract(self):
        with self.assertRaises(LabError):
            validate_descriptor(descriptor(source={"type": "archive", "path": "../image.tar"}))
        with self.assertRaisesRegex(LabError, "frr profile"):
            validate_descriptor(descriptor(profile="frr"))
        path = Path(__file__).resolve().parents[1] / "examples/device-packages/frr/device.json"
        result = validate_descriptor(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(result["profile"], "frr")
        self.assertEqual(result["actions"]["save_config"]["user"], "0")
        result["persistent_dirs"][0]["owner"] = "root:root"
        with self.assertRaisesRegex(LabError, "frr profile"):
            validate_descriptor(result)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "router.lwns"

    def tearDown(self):
        self.temp.cleanup()

    def package(self, raw=None, **kwargs):
        return pack_device(raw or descriptor(), self.output, **kwargs)

    def rewrite(self, name, body, update_manifest=False):
        with zipfile.ZipFile(self.output) as archive:
            files = {item.filename: archive.read(item.filename) for item in archive.infolist()}
        files[name] = body
        if update_manifest:
            manifest = json.loads(files["manifest.json"])
            manifest["files"][name] = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            files["manifest.json"] = canonical_json(manifest)
        with zipfile.ZipFile(self.output, "w") as archive:
            for filename, data in files.items():
                archive.writestr(filename, data)

    def test_repository_round_trip_without_execution(self):
        with patch("subprocess.run", side_effect=AssertionError("must not execute")):
            report = self.package()
            inspected = inspect_package(self.output)
        self.assertEqual(report, inspected)
        self.assertEqual(inspected["template_id"], template_id(descriptor()))
        self.assertEqual(set(inspected["resources"]), {"device.json"})
        self.assertEqual(len(inspected["package_sha256"]), 64)

    def test_archive_source_and_extraction(self):
        image = docker_archive(self.root / "arbitrary-upload-name")
        report = self.package(image_tar=image)
        self.assertEqual(report["descriptor"]["source"], {"type": "archive", "path": "image.tar"})
        target = self.root / "extracted"
        extracted = extract_package(self.output, target)
        self.assertEqual(extracted["package_sha256"], report["package_sha256"])
        self.assertEqual((target / "image.tar").read_bytes(), image.read_bytes())
        with self.assertRaisesRegex(LabError, "必须为空"):
            extract_package(self.output, target)

    def test_archive_missing_manifest_and_wrong_image_rejected(self):
        image = self.root / "invalid.tar"
        with tarfile.open(image, "w"):
            pass
        with self.assertRaisesRegex(LabError, "manifest.json"):
            self.package(image_tar=image)
        docker_archive(image, "unrelated/device:latest")
        with self.assertRaisesRegex(LabError, "不包含"):
            self.package(image_tar=image)
        self.assertFalse(self.output.exists())

    def test_recipe_is_two_authored_files_and_deterministic(self):
        dockerfile = self.root / "Dockerfile"
        dockerfile.write_text("FROM alpine:3.22\nCMD [\"sh\"]\n", encoding="utf-8")
        first = self.package(dockerfile=dockerfile)
        second = pack_device(descriptor(), self.root / "second.lwns", dockerfile=dockerfile)
        self.assertEqual(first["package_sha256"], second["package_sha256"])
        self.assertEqual(set(first["resources"]), {"device.json", "Dockerfile"})

    def test_source_requires_resource_and_cannot_mix(self):
        with self.assertRaisesRegex(LabError, "缺少来源文件"):
            self.package(descriptor(source={"type": "archive"}))
        with self.assertRaisesRegex(LabError, "一种来源"):
            self.package(image_tar="a", dockerfile="b")

    def test_output_requires_extension_and_never_overwrites_without_force(self):
        self.package()
        original = self.output.read_bytes()
        with self.assertRaisesRegex(LabError, "拒绝覆盖"):
            self.package(descriptor(name="changed"))
        self.assertEqual(self.output.read_bytes(), original)
        with self.assertRaisesRegex(LabError, ".lwns"):
            pack_device(descriptor(), self.root / "wrong.zip")

    def test_bad_checksum_and_unexpected_resources(self):
        self.package()
        definition = validate_descriptor(descriptor(name="tampered"))
        self.rewrite("device.json", canonical_json(definition))
        with self.assertRaisesRegex(LabError, "清单无效|校验失败"):
            inspect_package(self.output)
        self.package(overwrite=True)
        self.rewrite("../escape", b"bad")
        with self.assertRaisesRegex(LabError, "路径|重复"):
            inspect_package(self.output)

    def test_links_and_duplicate_entries_are_rejected(self):
        self.package()
        with zipfile.ZipFile(self.output, "a") as archive:
            item = zipfile.ZipInfo("image.tar")
            item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "outside")
        with self.assertRaisesRegex(LabError, "链接"):
            inspect_package(self.output)
        self.package(overwrite=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.output, "a") as archive:
                archive.writestr("device.json", "{}")
        with self.assertRaisesRegex(LabError, "重复"):
            inspect_package(self.output)

    def test_inspect_rejects_semantically_changed_descriptor_even_with_new_hash(self):
        self.package()
        raw = descriptor()
        raw["actions"] = {}
        self.rewrite("device.json", canonical_json(raw), update_manifest=True)
        with self.assertRaisesRegex(LabError, "save_config"):
            inspect_package(self.output)

    def test_invalid_package_does_not_create_extraction_directory(self):
        self.output.write_bytes(b"not a zip")
        destination = self.root / "no-extraction"
        with self.assertRaises(LabError):
            extract_package(self.output, destination)
        self.assertFalse(destination.exists())

    def test_compressed_or_oversized_payload_is_bounded(self):
        self.package()
        with patch("lab_device_packages.MAX_PACKAGE", 16):
            with self.assertRaisesRegex(LabError, "大小限制"):
                inspect_package(self.output)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "device.lwns"
        self.report = pack_device(descriptor(), self.package)
        self.library = DeviceLibrary(self.root / "data")
        self.image_id = "sha256:" + "a" * 64

    def tearDown(self):
        self.temp.cleanup()

    def register(self, **kwargs):
        return self.library.register(self.package, image_id=self.image_id, **kwargs)

    def test_register_catalog_pinned_image_and_restart(self):
        entry = self.register(name="我的路由器")
        self.assertEqual(entry["image"], "test/router:one")
        template = self.library.resolve(entry["id"])
        self.assertEqual(template["image"], self.image_id)
        self.assertEqual(template["image_reference"], entry["image"])
        self.assertEqual(template["profile"], "generic")
        self.assertEqual(template["title"], "我的路由器")
        self.assertTrue(template["managed"])
        self.assertTrue(template["capabilities"]["save_config"])
        self.assertFalse(template["capabilities"]["startup_config"])
        again = DeviceLibrary(self.root / "data")
        self.assertEqual(again.entries(), [entry])
        self.assertEqual(again.package_path(entry["id"]).read_bytes(), self.package.read_bytes())

    def test_same_content_idempotent_and_rename_preserves_package(self):
        first = self.register()
        self.assertEqual(self.register(), first)
        renamed = self.library.rename(first["id"], "新名字")
        self.assertEqual(renamed["package_sha256"], first["package_sha256"])
        self.assertEqual(self.library.descriptor(first["id"])["name"], descriptor()["name"])
        self.assertEqual(self.library.resolve(first["id"])["title"], "新名字")

    def test_legacy_extension_and_installed_archive_remain_usable(self):
        legacy = self.package.with_suffix(".rov")
        self.package.rename(legacy)
        entry = self.library.register(legacy, image_id=self.image_id)
        installed = self.library.package_path(entry["id"])
        self.assertEqual(installed.name, "device.lwns")
        old_installed = installed.with_suffix(".rov")
        installed.rename(old_installed)
        restarted = DeviceLibrary(self.root / "data")
        self.assertEqual(restarted.package_path(entry["id"]), old_installed)
        self.assertEqual(restarted.register(legacy, image_id=self.image_id), entry)
        restarted.remove(entry["id"])
        self.assertFalse(old_installed.exists())

    def test_same_version_conflict_and_new_version_keeps_previous(self):
        first = self.register()
        pack_device(descriptor(name="different"), self.package, overwrite=True)
        with self.assertRaisesRegex(LabError, "新版本"):
            self.register()
        pack_device(descriptor(version="1.1.0"), self.package, overwrite=True)
        second = self.register()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.library.entries()), 2)
        self.assertEqual(self.library.resolve(first["id"])["descriptor_version"], "1.0.0")

    def test_short_version_round_trip_preserves_existing_patch_version(self):
        existing = self.register()
        report = pack_device(descriptor(version="1.0"), self.package, overwrite=True)
        self.assertEqual(report["descriptor"]["version"], "1.0")
        short = self.register()
        self.assertNotEqual(short["id"], existing["id"])
        restarted = DeviceLibrary(self.root / "data")
        self.assertEqual(restarted.resolve(short["id"])["descriptor_version"], "1.0")
        self.assertEqual(restarted.package_path(short["id"]).parent.name, "1.0")
        self.assertEqual(restarted.resolve(existing["id"])["descriptor_version"], "1.0.0")

    def test_same_name_different_identity_not_overwritten(self):
        first = self.register()
        pack_device(descriptor(id="other-router"), self.package, overwrite=True)
        second = self.register()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.library.entries()), 2)

    def test_remove_blocks_references_and_preserves_instance_files(self):
        entry = self.register()
        config = self.root / "data/devices/lab/r1/config"
        config.parent.mkdir(parents=True)
        config.write_text("saved", encoding="utf-8")
        with self.assertRaisesRegex(LabError, "引用"):
            self.library.remove(entry["id"], referenced={entry["id"]})
        self.library.remove(entry["id"])
        self.assertEqual(self.library.catalog(), [])
        self.assertEqual(config.read_text(), "saved")
        with self.assertRaises(LabError):
            self.library.resolve(entry["id"])

    def test_same_version_cannot_rebind_mutable_tag(self):
        self.register()
        with self.assertRaisesRegex(LabError, "不同镜像"):
            self.library.register(self.package, image_id="sha256:" + "b" * 64)

    def test_no_prepared_image_is_not_a_usable_catalog_device(self):
        entry = self.library.register(self.package)
        self.assertEqual(self.library.catalog(), [])
        self.assertEqual(len(self.library.entries()), 1)
        with self.assertRaisesRegex(LabError, "尚未准备"):
            self.library.resolve(entry["id"])
        self.register()
        self.assertEqual(self.library.resolve(entry["id"])["image"], self.image_id)


class CliTests(unittest.TestCase):
    def test_source_entrypoint_packages_both_examples_without_site_packages(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            for example_name in ("frr", "config-demo"):
                example = project / "examples/device-packages" / example_name
                self.assertEqual({item.name for item in example.iterdir()}, {"device.json", "Dockerfile"})
                output = Path(directory) / (example_name + ".lwns")
                result = subprocess.run([
                    sys.executable, "-S", str(project / "script/python/lab_server.py"), "device", "pack",
                    "--descriptor", str(example / "device.json"), "--dockerfile", str(example / "Dockerfile"),
                    "--output", str(output),
                ], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["descriptor"]["source"]["type"], "dockerfile")
                checked = inspect_package(output)
                self.assertEqual(checked["package_sha256"], json.loads(result.stdout)["package_sha256"])

    def test_pack_and_inspect_share_format_without_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "device.json"
            source.write_bytes(canonical_json(descriptor()))
            output = root / "device.lwns"
            with patch("subprocess.run", side_effect=AssertionError("unexpected command")), contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(main(["pack", "--descriptor", str(source), "--output", str(output)]), 0)
            made = json.loads(stream.getvalue())
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(main(["device", "inspect", str(output)]), 0)
            self.assertEqual(made, json.loads(stream.getvalue()))

    def test_failure_returns_nonzero_and_does_not_create_package(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.lwns"
            path.write_text("invalid")
            with contextlib.redirect_stderr(io.StringIO()) as stream:
                self.assertEqual(main(["inspect", str(path)]), 1)
            self.assertIn("失败", stream.getvalue())

    def test_cli_mutation_lock_matches_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            with library_lock(Path(directory)):
                with self.assertRaisesRegex(LabError, "正由后端"):
                    with library_lock(Path(directory)):
                        self.fail("second lock must fail")


if __name__ == "__main__":
    unittest.main()
