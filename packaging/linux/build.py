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
import sysconfig
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


def verify_source_archive(archive, root):
    """Require the recorded source to match the actual build inputs."""
    checked = 0
    prefix = None
    seen = set()
    with tarfile.open(archive, "r:*") as source:
        for entry in source.getmembers():
            name = Path(entry.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError("Unsafe source archive path: " + entry.name)
            if prefix is None:
                prefix = name.parts[0]
            if name.parts[0] != prefix or entry.name in seen:
                raise ValueError("Source archive must have one unique top-level directory")
            seen.add(entry.name)
            path = root.joinpath(*name.parts[1:])
            if entry.isdir():
                if not path.is_dir() or path.is_symlink():
                    raise ValueError("Source directory differs: " + entry.name)
            elif entry.isfile():
                if not path.is_file() or path.is_symlink():
                    raise ValueError("Source file missing or replaced: " + entry.name)
                checksum = hashlib.sha256()
                with source.extractfile(entry) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(block)
                if checksum.hexdigest() != digest(path):
                    raise ValueError("Source file changed after snapshot: " + entry.name)
                checked += 1
            elif entry.issym():
                if not path.is_symlink() or os.readlink(path) != entry.linkname:
                    raise ValueError("Source symlink differs: " + entry.name)
                if not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError("External source symlink: " + entry.name)
            else:
                raise ValueError("Unsupported source archive entry: " + entry.name)
    if not checked:
        raise ValueError("Source archive contains no files")
    return checked


def copy_notices(package):
    notices = package / "THIRD_PARTY"
    notices.mkdir()
    for dist in importlib.metadata.distributions():
        name = re.sub(r"[^A-Za-z0-9._-]", "_", dist.metadata["Name"])
        for item in dist.files or ():
            if not any(part.lower().startswith(("license", "copying", "notice")) for part in item.parts):
                continue
            source = Path(dist.locate_file(item))
            if source.is_file():
                target = notices / name / item.name
                target.parent.mkdir(exist_ok=True)
                # Keep distinct notices instead of silently replacing one.
                if target.exists() and target.read_bytes() != source.read_bytes():
                    target = target.with_name(digest(source)[:12] + "-" + target.name)
                shutil.copyfile(source, target)
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, notices / "Python-LICENSE.txt")
    for name in ("libc6", "libssl3", "zlib1g", "libbz2-1.0", "liblzma5", "libffi8", "libexpat1"):
        copyright_file = Path("/usr/share/doc") / name / "copyright"
        if copyright_file.is_file():
            shutil.copyfile(copyright_file, notices / (name + "-copyright.txt"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Release version; defaults to the source web/package.json")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument("--skip-web-build", action="store_true", help="Use an already built web/dist")
    parser.add_argument("--compression", choices=("xz", "gz"), default="xz")
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Clean source snapshot to package")
    parser.add_argument("--source-revision", help="Full Git commit of the source snapshot")
    parser.add_argument("--source-tag", help="Git tag associated with the release")
    parser.add_argument("--source-archive", type=Path, help="Original git archive with a single directory prefix")
    parser.add_argument("--docs-dir", type=Path, help="Built HTML documentation directory")
    parser.add_argument("--verification-report", type=Path, help="Actual pre-publication test results")
    parser.add_argument("--release", action="store_true", help="Require source provenance, HTML manual and validation report")
    args = parser.parse_args()
    root = args.source_root.resolve()
    source_packaging = root / "packaging/linux"
    args.version = args.version or json.loads((root / "web/package.json").read_text())["version"]
    if sys.platform != "linux" or platform.libc_ver()[0] != "glibc":
        parser.error("Build on a glibc Linux host for the target architecture.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", args.version):
        parser.error("Invalid version")
    if args.source_revision and not re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", args.source_revision):
        parser.error("Use a full Git commit for --source-revision")
    if args.source_tag and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", args.source_tag):
        parser.error("Invalid source tag")
    if args.release and not all((args.source_revision, args.source_tag, args.source_archive,
                                 args.docs_dir, args.verification_report)):
        parser.error("--release requires --source-revision, --source-tag, --source-archive, --docs-dir and --verification-report")
    if args.docs_dir and not (args.docs_dir / "index.html").is_file():
        parser.error("--docs-dir must contain a built index.html")
    if args.verification_report and (not args.verification_report.is_file() or not args.verification_report.stat().st_size):
        parser.error("--verification-report must be a nonempty file")
    if args.source_archive:
        verify_source_archive(args.source_archive, root)
    if not args.skip_web_build:
        subprocess.run(["npm", "--prefix", str(root / "web"), "run", "build"], check=True)
    if not (root / "web/dist/index.html").is_file():
        parser.error("Build web/dist before packaging.")
    name = f"lwns-{args.version}-linux-{platform.machine()}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (name + ".tar." + args.compression)
    if archive.exists() or archive.with_suffix(archive.suffix + ".sha256").exists():
        parser.error("Release already exists; choose a new --version or --output.")
    # Build locally: Samba checkouts may not support the symlinks used by PyInstaller.
    with tempfile.TemporaryDirectory(prefix="lwns-build-") as temporary:
        work = Path(temporary)
        command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                   "--name", "lwns", "--distpath", str(work / "dist"),
                   "--workpath", str(work / "work"), "--specpath", str(work),
                   "--paths", str(root / "script/python"),
                   "--collect-submodules", "uvicorn", "--collect-submodules", "websockets",
                   "--hidden-import", "anyio._backends._asyncio"]
        resources = [(root / "web/dist", "web/dist"),
                     (root / "config/images.defaults.json", "config"),
                     (root / "examples/basic-lab.json", "examples"),
                     (root / "examples/device-packages", "examples/device-packages")]
        for filename in ("launcher.py", "remote_relay.py", "configure.ps1", "install.ps1", "install.sh", "README.md"):
            resources.append((root / "clients/capture" / filename, "clients/capture"))
        for source, destination in resources:
            command += ["--add-data", str(source) + ":" + destination]
        command.append(str(root / "script/python/lab_server.py"))
        subprocess.run(command, check=True, cwd=root,
                       env={**os.environ, "PYINSTALLER_CONFIG_DIR": str(work / "cache")})
        package = work / name
        package.mkdir()
        shutil.move(str(work / "dist/lwns"), package / "app")
        for filename in ("run.sh", "uninstall.sh"):
            shutil.copy2(source_packaging / filename, package / "app" / filename)
            (package / "app" / filename).chmod(0o755)
        shutil.copy2(source_packaging / "install.sh", package / "install.sh")
        (package / "install.sh").chmod(0o755)
        shutil.copy2(source_packaging / "lwns-web.service", package / "lwns-web.service")
        shutil.copy2(root / "config/Caddyfile", package / "Caddyfile.example")
        shutil.copy2(root / "docs/user/workbench-install.rst", package / "INSTALL.rst")
        shutil.copy2(HERE / "README.md", package / "README.md")
        tools_dir = package / "build-tools"
        tools_dir.mkdir()
        shutil.copy2(Path(__file__), tools_dir / "build.py")
        shutil.copy2(HERE / "README.md", tools_dir / "README.md")
        if args.docs_dir:
            shutil.copytree(args.docs_dir, package / "docs/html", ignore=shutil.ignore_patterns(".doctrees"))
        if args.source_archive:
            (package / "sources").mkdir()
            shutil.copyfile(args.source_archive, package / "sources" / args.source_archive.name)
        if args.verification_report:
            shutil.copyfile(args.verification_report, package / "VERIFICATION.md")
        for license_file in root.glob("LICENSE*"):
            if license_file.is_file():
                shutil.copy2(license_file, package / license_file.name)
        copy_notices(package)
        now = datetime.now(timezone.utc)
        build_id = args.version + "-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        (package / "BUILD_ID").write_text(build_id + "\n")
        metadata = {"version": args.version, "build_id": build_id, "architecture": platform.machine(),
                    "libc": platform.libc_ver(), "python": platform.python_version(),
                    "source_revision": args.source_revision, "source_tag": args.source_tag,
                    "source_archive_sha256": digest(args.source_archive) if args.source_archive else None,
                    "packaging_tool_sha256": digest(Path(__file__)),
                    "built_at": now.isoformat(), "dependencies": {
                        dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}}
        (package / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
        shutil.copy2(package / "build-info.json", package / "app/build-info.json")
        (package / "build-requirements.txt").write_text("\n".join(
            name + "==" + version for name, version in sorted(metadata["dependencies"].items(), key=lambda item: item[0].lower())) + "\n")
        lines = []
        for path in sorted(package.rglob("*")):
            if path.is_symlink() and not path.resolve().is_relative_to(package.resolve()):
                raise RuntimeError("External symlink in package: " + str(path))
            if path.is_file():
                lines.append(digest(path) + "  " + path.relative_to(package).as_posix())
        (package / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        temporary_archive = work / archive.name
        with tarfile.open(temporary_archive, "w:" + args.compression, dereference=False) as tar:
            tar.add(package, arcname=name)
        shutil.copyfile(temporary_archive, archive)
        archive.with_suffix(archive.suffix + ".sha256").write_text(digest(archive) + "  " + archive.name + "\n")
    print("Release: " + str(archive))
    print("Runtime compatibility: " + platform.machine() + ", glibc build baseline " + platform.libc_ver()[1])


if __name__ == "__main__":
    main()
