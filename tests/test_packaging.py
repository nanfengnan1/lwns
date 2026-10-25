"""Paths and host library isolation required by the frozen Linux runtime."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script/python"))
import lab_paths
from lab_core import execute


class PackagingRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux installed command wrapper")
    def test_installed_wrapper_dispatches_device_cli_without_server_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "run.sh"
            shutil.copyfile(Path(__file__).resolve().parents[1] / "packaging/linux/run.sh", wrapper)
            executable = root / "lwns"
            executable.write_text("#!/usr/bin/env python3\nimport json,os,sys\n"
                                  "print(json.dumps({'argv':sys.argv[1:],'data':os.environ.get('LWNS_DATA_DIR')}))\n")
            executable.chmod(0o755)
            config = root / "test.env"
            config.write_text("LWNS_HOST=127.0.0.2\nLWNS_PORT=19090\nLWNS_DATA_DIR=/tmp/test-device-data\n")
            env = {**os.environ, "LWNS_CONFIG_FILE": str(config)}
            command = ["bash", str(wrapper), "device", "pack", "--output", "my device.rov"]
            result = json.loads(subprocess.run(command, env=env, text=True, capture_output=True, check=True).stdout)
            self.assertEqual(result["argv"], ["device", "pack", "--output", "my device.rov"])
            self.assertEqual(result["data"], "/tmp/test-device-data")
            server = json.loads(subprocess.run(["bash", str(wrapper), "--preview"], env=env,
                                               text=True, capture_output=True, check=True).stdout)
            self.assertEqual(server["argv"][:6], ["--host", "127.0.0.2", "--port", "19090", "--data-dir", "/tmp/test-device-data"])
            self.assertIn("--preview", server["argv"])
            # Existing installations can copy the old env file without losing
            # their data path; explicit new variables take precedence.
            config.write_text("ROUTE_OVS_HOST=127.0.0.3\nROUTE_OVS_PORT=19091\nROUTE_OVS_DATA_DIR=/tmp/legacy-labs\n")
            env.pop("LWNS_CONFIG_FILE")
            env["ROUTE_OVS_CONFIG_FILE"] = str(config)
            server = json.loads(subprocess.run(["bash", str(wrapper)], env=env,
                                               text=True, capture_output=True, check=True).stdout)
            self.assertEqual(server["argv"][:6], ["--host", "127.0.0.3", "--port", "19091", "--data-dir", "/tmp/legacy-labs"])
            env["LWNS_DATA_DIR"] = "/tmp/new-labs"
            result = json.loads(subprocess.run(command, env=env, text=True, capture_output=True, check=True).stdout)
            self.assertEqual(result["data"], "/tmp/new-labs")

    def test_source_paths_remain_compatible(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(lab_paths.resource_root(), Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "frozen", False, create=True), patch.dict(os.environ, {}, clear=True), patch.object(lab_paths, "resource_root", return_value=Path(temporary)):
            current, legacy = Path(temporary) / ".lwns-labs", Path(temporary) / ".route-ovs-labs"
            self.assertEqual(lab_paths.default_data_dir(), current)
            legacy.mkdir()
            (legacy / "project.json").write_text('{"name":"existing project"}')
            self.assertEqual(lab_paths.default_data_dir(), legacy)
            self.assertFalse(current.exists())
            current.mkdir()
            self.assertEqual(lab_paths.default_data_dir(), current)
            self.assertTrue((legacy / "project.json").is_file())

    def test_renamed_environment_preserves_explicit_data_and_token(self):
        with patch.dict(os.environ, {"ROUTE_OVS_DATA_DIR": "/legacy", "ROUTE_OVS_TOKEN": "legacy-token"}, clear=True):
            self.assertEqual(lab_paths.default_data_dir(), Path("/legacy"))
            self.assertEqual(lab_paths.environment_setting("TOKEN"), "legacy-token")
            with patch.dict(os.environ, {"LWNS_DATA_DIR": "/current", "LWNS_TOKEN": "new-token"}):
                self.assertEqual(lab_paths.default_data_dir(), Path("/current"))
                self.assertEqual(lab_paths.environment_setting("TOKEN"), "new-token")

    def test_frozen_resources_and_writable_data_are_separate(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", "/opt/lwns/releases/example/_internal", create=True), patch.dict(os.environ, {}, clear=True), patch.object(Path, "exists", return_value=False), patch.object(Path, "is_dir", return_value=False):
            self.assertEqual(lab_paths.resource_root(), Path(sys._MEIPASS))
            self.assertEqual(lab_paths.default_data_dir(), Path("/var/lib/lwns"))

    def test_host_command_restores_original_library_path_without_mutating_parent(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/host", "KEEP_ME": "yes"}, clear=True):
            env = lab_paths.host_environment()
            self.assertEqual(env["LD_LIBRARY_PATH"], "/host")
            self.assertNotIn("LD_LIBRARY_PATH_ORIG", env)
            self.assertEqual(env["KEEP_ME"], "yes")
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/bundle")

    @unittest.skipUnless(sys.platform == "linux", "Linux host-command environment")
    def test_real_host_subprocess_does_not_inherit_frozen_library_path(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": "/bundle"}, clear=True):
            output = execute(["/usr/bin/env"]).stdout
            self.assertNotIn("LD_LIBRARY_PATH", output)
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/bundle")

    def test_source_process_environment_is_unchanged(self):
        with patch.object(sys, "frozen", False, create=True), patch.dict(os.environ, {"LD_LIBRARY_PATH": "/custom"}, clear=True):
            self.assertEqual(lab_paths.host_environment(), dict(os.environ))


if __name__ == "__main__":
    unittest.main()
