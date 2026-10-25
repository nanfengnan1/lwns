#!/usr/bin/env python3
"""Build a Linux onedir release without copying local data or credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=json.loads((ROOT / "web/package.json").read_text())["version"])
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--skip-web-build", action="store_true", help="Use an already built web/dist")
    args = parser.parse_args()
    if sys.platform != "linux" or platform.libc_ver()[0] != "glibc":
        parser.error("Build on a glibc Linux host for the target architecture.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", args.version):
        parser.error("Invalid version")
    if not args.skip_web_build:
        subprocess.run(["npm", "--prefix", str(ROOT / "web"), "run", "build"], check=True)
    if not (ROOT / "web/dist/index.html").is_file():
        parser.error("Build web/dist before packaging.")
    name = f"lwns-{args.version}-linux-{platform.machine()}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (name + ".tar.gz")
    if archive.exists() or archive.with_suffix(archive.suffix + ".sha256").exists():
        parser.error("Release already exists; choose a new --version or --output.")
    # Build locally: Samba checkouts may not support the symlinks used by PyInstaller.
    with tempfile.TemporaryDirectory(prefix="lwns-build-") as temporary:
        work = Path(temporary)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                   "--name", "lwns", "--distpath", str(work / "dist"),
                   "--workpath", str(work / "work"), "--specpath", str(work),
                   "--paths", str(ROOT / "script/python"),
                   "--collect-submodules", "uvicorn", "--collect-submodules", "websockets",
                   "--hidden-import", "anyio._backends._asyncio"]
        resources = [(ROOT / "web/dist", "web/dist"),
                     (ROOT / "config/images.defaults.json", "config"),
                     (ROOT / "examples/basic-lab.json", "examples"),
                     (ROOT / "examples/device-packages", "examples/device-packages")]
        for filename in ("launcher.py", "remote_relay.py", "configure.ps1", "install.ps1", "install.sh", "README.md"):
            resources.append((ROOT / "clients/capture" / filename, "clients/capture"))
        for source, destination in resources:
            command += ["--add-data", str(source) + ":" + destination]
        command.append(str(ROOT / "script/python/lab_server.py"))
        subprocess.run(command, check=True, cwd=ROOT,
                       env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(work / "cache")})
        package = work / name
        package.mkdir()
        shutil.move(str(work / "dist/lwns"), package / "app")
        for filename in ("run.sh", "uninstall.sh"):
            shutil.copy2(HERE / filename, package / "app" / filename)
            (package / "app" / filename).chmod(0o755)
        shutil.copy2(HERE / "install.sh", package / "install.sh")
        (package / "install.sh").chmod(0o755)
        shutil.copy2(HERE / "lwns-web.service", package / "lwns-web.service")
        shutil.copy2(ROOT / "config/Caddyfile", package / "Caddyfile.example")
        shutil.copy2(ROOT / "docs/user/workbench-install.rst", package / "INSTALL.rst")
        now = datetime.now(timezone.utc)
        build_id = args.version + "-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        (package / "BUILD_ID").write_text(build_id + "\n")
        metadata = {"version": args.version, "build_id": build_id, "architecture": platform.machine(),
                    "libc": platform.libc_ver(), "python": platform.python_version(),
                    "built_at": now.isoformat(), "dependencies": {
                        dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}}
        (package / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
        shutil.copy2(package / "build-info.json", package / "app/build-info.json")
        lines = []
        for path in sorted(package.rglob("*")):
            if path.is_symlink() and not path.resolve().is_relative_to(package.resolve()):
                raise RuntimeError("External symlink in package: " + str(path))
            if path.is_file():
                lines.append(digest(path) + "  " + path.relative_to(package).as_posix())
        (package / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        temporary_archive = work / (name + ".tar.gz")
        with tarfile.open(temporary_archive, "w:gz", dereference=False) as tar:
            tar.add(package, arcname=name)
        shutil.copyfile(temporary_archive, archive)
        archive.with_suffix(archive.suffix + ".sha256").write_text(digest(archive) + "  " + archive.name + "\n")
    print("Release: " + str(archive))
    print("Runtime compatibility: " + platform.machine() + ", glibc build baseline " + platform.libc_ver()[1])


if __name__ == "__main__":
    main()
