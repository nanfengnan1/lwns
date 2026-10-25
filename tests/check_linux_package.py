#!/usr/bin/env python3
"""Exercise a real directory release in an isolated staging root; no Docker mutations."""
import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile


def run(*args, ok=True, env=None):
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    if (result.returncode == 0) != ok:
        raise AssertionError(f"Unexpected command result ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
    return result


def manifest(package):
    lines = []
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(package).as_posix())
    (package / "SHA256SUMS").write_text("\n".join(lines) + "\n")


async def websocket_check(port):
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    async with connect(f"ws://127.0.0.1:{port}/api/terminal", origin=f"http://127.0.0.1:{port}", proxy=None) as ws:
        await ws.send(json.dumps({"type": "connect", "ticket": "invalid", "cols": 80, "rows": 24}))
        message = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert message["type"] == "error" and "凭证" in message["message"], message
        try:
            while True:
                await asyncio.wait_for(ws.recv(), 5)
        except ConnectionClosed as closed:
            assert closed.rcvd.code == 1000, closed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args().archive.resolve()
    with tempfile.TemporaryDirectory(prefix="lwns-package-check-") as temporary:
        temp = Path(temporary)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                for name in (member.name, member.linkname):
                    if name and (PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts):
                        raise ValueError("Unsafe test archive member: " + name)
                if not (member.isfile() or member.isdir() or member.issym()):
                    raise ValueError("Unexpected archive entry type")
            tar.extractall(temp / "unpacked")
        package, = (temp / "unpacked").iterdir()
        stage = temp / "system"
        data = temp / "labs"
        install = ["bash", str(package / "install.sh"), "--root", str(stage), "--no-systemd", "--data-dir", str(data)]

        # Check integrity failure before any installation state is written.
        build = package / "BUILD_ID"
        original_id = build.read_text()
        build.write_text(original_id.strip() + "-tampered\n")
        run(*install, ok=False)
        assert not (stage / "opt/lwns").exists()
        build.write_text(original_id)

        # A foreign unit and a symlinked path must be preserved, not overwritten.
        unit = stage / "etc/systemd/system/lwns-web.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Service]\nExecStart=/someone/elses/server\n")
        run(*install, ok=False)
        assert "/someone/elses" in unit.read_text()
        assert not (stage / "opt/lwns").exists()
        unit.unlink()
        (stage / "opt").symlink_to(temp / "outside")
        run(*install, ok=False)
        assert not (temp / "outside").exists()
        (stage / "opt").unlink()

        run(*install)
        current = stage / "opt/lwns/current"
        first_release = current.resolve()
        config = stage / "etc/lwns/lwns.env"
        original_config = config.read_bytes()
        assert config.stat().st_mode & 0o777 == 0o600
        token = re.search(r"^LWNS_TOKEN=([a-f0-9]+)$", config.read_text(), re.M)[1]
        assert len(token) == 64
        assert first_release.joinpath("_internal/config/images.defaults.json").is_file()
        assert not unit.exists(), "Staging modified a service file"
        assert not (current / ".lwns-labs").exists()

        # Launch through the installed command, outside the checkout and without Python.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = temp / "server.log"
        env = {**os.environ, "PATH": "/usr/bin:/bin", "LWNS_CONFIG_FILE": str(config)}
        with log.open("wb") as stream:
            proc = subprocess.Popen([str(stage / "usr/local/bin/lwns"), "--preview", "--port", str(port)],
                                    cwd=temp, env=env, stdout=stream, stderr=stream)
        base = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path, authenticated=True, headers=None):
            return opener.open(urllib.request.Request(base + path, headers={
                **({"Authorization": "Bearer " + token} if authenticated else {}), **(headers or {})}), timeout=5)

        try:
            for _ in range(100):
                try:
                    with get("/") as response:
                        html = response.read().decode()
                    break
                except OSError:
                    if proc.poll() is not None:
                        raise RuntimeError("Frozen server exited; log: " + log.read_text().replace(token, "[TOKEN]"))
                    time.sleep(.1)
            else:
                raise RuntimeError("Frozen server did not start")
            asset = re.search(r'src="(/assets/[^" ]+\.js)"', html)[1]
            with get(asset, headers={"Accept-Encoding": "gzip"}) as response:
                assert response.headers["Content-Encoding"] == "gzip"
                assert "immutable" in response.headers["Cache-Control"]
            with get("/api/bootstrap") as response:
                bootstrap = json.load(response)
                assert bootstrap["labs"] == []
                assert "example" not in bootstrap
                assert bootstrap["catalog"]
            with get("/api/capture/client") as response:
                with zipfile.ZipFile(io.BytesIO(response.read())) as client:
                    assert "remote_relay.py" in client.namelist()
            try:
                get("/api/labs", authenticated=False)
                raise AssertionError("Unauthenticated API was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 401
            asyncio.run(websocket_check(port))
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        assert proc.returncode == 0, log.read_text().replace(token, "[TOKEN]")

        # Install again, then upgrade to a second immutable build, preserving state.
        data.mkdir(exist_ok=True)
        (data / "keep.txt").write_text("experiment/config sentinel")
        run(*install)
        build.write_text(original_id.strip() + "-upgrade\n")
        manifest(package)
        run(*install)
        assert current.resolve() != first_release and first_release.is_dir()
        assert config.read_bytes() == original_config
        assert (data / "keep.txt").read_text() == "experiment/config sentinel"

        # Every new host gets a different secret.
        stage2 = temp / "another-system"
        run("bash", str(package / "install.sh"), "--root", str(stage2), "--no-systemd")
        assert token not in (stage2 / "etc/lwns/lwns.env").read_text()

        run("bash", str(current / "uninstall.sh"), "--root", str(stage), "--no-systemd")
        assert not (stage / "opt/lwns").exists()
        assert not (stage / "usr/local/bin/lwns").is_symlink()
        assert config.read_bytes() == original_config and (data / "keep.txt").exists()
    print(json.dumps({"frozen_http": True, "static_gzip": True, "resource_paths": True,
                      "auth": True, "websocket": True, "integrity_rejection": True,
                      "foreign_install_rejection": True, "upgrade_preserves_config_data": True,
                      "unique_tokens": True, "uninstall_preserves_config_data": True}))


if __name__ == "__main__":
    main()
