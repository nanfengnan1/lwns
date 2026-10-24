"""Opt-in real TLS/proxy test; no Docker changes or system trust installation.

Needs local Linux Docker info access (no load/deploy), project test dependencies
plus httpx[http2]; --http3 needs aioquic.
  .venv/bin/python tests/check_caddy.py --caddy /path/to/caddy --http3
"""
import argparse
import asyncio
import gzip
import io
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def check_websocket(base, context):
    context.set_alpn_protocols(["http/1.1"])
    async with connect(base.replace("https:", "wss:") + "/api/terminal", ssl=context, origin=base, proxy=None) as ws:
        await ws.send(json.dumps({"type": "connect", "ticket": "invalid", "cols": 80, "rows": 24}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "error"
    try:
        async with connect(base.replace("https:", "wss:") + "/api/terminal", ssl=context,
                           origin="https://foreign.example", proxy=None):
            raise AssertionError("Foreign WebSocket origin was accepted")
    except InvalidStatus as exc:
        assert exc.response.status_code == 403


async def check_http3(port, root_cert, path, expected):
    from aioquic.asyncio import connect as quic_connect, QuicConnectionProtocol
    from aioquic.h3.connection import H3_ALPN, H3Connection
    from aioquic.h3.events import DataReceived, HeadersReceived
    from aioquic.quic.configuration import QuicConfiguration

    class Client(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.http = H3Connection(self._quic)
            self.done = asyncio.get_running_loop().create_future()
            self.headers, self.body = {}, bytearray()

        def quic_event_received(self, event):
            for item in self.http.handle_event(event):
                if isinstance(item, HeadersReceived):
                    self.headers.update(item.headers)
                if isinstance(item, DataReceived):
                    self.body.extend(item.data)
                if isinstance(item, (HeadersReceived, DataReceived)) and item.stream_ended and not self.done.done():
                    self.done.set_result((self.headers, bytes(self.body)))

        async def get(self):
            stream = self._quic.get_next_available_stream_id()
            self.http.send_headers(stream, [(b":method", b"GET"), (b":scheme", b"https"),
                (b":authority", f"127.0.0.1:{port}".encode()), (b":path", path.encode()),
                (b"accept-encoding", b"gzip")], end_stream=True)
            self.transmit()
            return await asyncio.wait_for(self.done, 15)

    configuration = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    configuration.load_verify_locations(cafile=str(root_cert))
    async with quic_connect("127.0.0.1", port, configuration=configuration, create_protocol=Client) as client:
        headers, body = await client.get()
        assert headers[b":status"] == b"200", headers
        assert headers[b"content-encoding"] == b"gzip", headers
        assert gzip.decompress(body) == expected
        return len(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", required=True)
    parser.add_argument("--http3", action="store_true")
    args = parser.parse_args()
    processes = []
    with tempfile.TemporaryDirectory(prefix="route-ovs-caddy-") as directory:
        temp = Path(directory)
        backend_port, tls_port = free_port(), free_port()
        base = f"https://127.0.0.1:{tls_port}"
        config = re.sub(r"(?m)^\{$", "{\n    admin off\n    auto_https disable_redirects",
                        (ROOT / "config/Caddyfile").read_text(encoding="utf-8"), count=1)
        config = config.replace("    tls internal", "    bind 127.0.0.1\n    tls internal").replace(
            "\ttls internal", "\tbind 127.0.0.1\n\ttls internal")
        config_path = temp / "Caddyfile"
        config_path.write_text(config, encoding="utf-8")
        env = {**os.environ, "ROUTE_OVS_SITE": base, "ROUTE_OVS_UPSTREAM": f"127.0.0.1:{backend_port}",
               "ROUTE_OVS_TOKEN": "delivery-check", "XDG_DATA_HOME": str(temp / "data"),
               "XDG_CONFIG_HOME": str(temp / "config")}
        with (temp / "processes.log").open("w+") as log:
            try:
                subprocess.run([args.caddy, "validate", "--config", str(config_path), "--adapter", "caddyfile"],
                               env=env, stdout=log, stderr=log, check=True)
                processes.append(subprocess.Popen([sys.executable, str(ROOT / "script/python/lab_server.py"),
                    "--port", str(backend_port), "--data-dir", str(temp / "labs"),
                    "--trusted-proxy", "127.0.0.1"], env=env, stdout=log, stderr=log))
                processes.append(subprocess.Popen([args.caddy, "run", "--config", str(config_path),
                    "--adapter", "caddyfile"], env=env, stdout=log, stderr=log))
                root_cert = temp / "data/caddy/pki/authorities/local/root.crt"
                for _ in range(200):
                    try:
                        if root_cert.exists():
                            context = ssl.create_default_context(cafile=str(root_cert))
                            with httpx.Client(verify=context, trust_env=False, timeout=1) as probe:
                                if probe.get(base).status_code == 200:
                                    break
                    except (httpx.HTTPError, ssl.SSLError):
                        pass
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError("Test service exited early")
                    time.sleep(.1)
                else:
                    raise RuntimeError("Test services did not start")
                headers = {"Authorization": "Bearer delivery-check", "Origin": base}
                with httpx.Client(verify=context, http2=True, trust_env=False, timeout=15) as client:
                    html = client.get(base)
                    assert html.http_version == "HTTP/2", html.http_version
                    assert "h3=" in html.headers["alt-svc"]
                    assert html.headers["cache-control"] == "no-cache"
                    asset = re.search(r'src="(/assets/[^\"]+\.js)"', html.text)[1]
                    response = client.get(base + asset, headers={"Accept-Encoding": "gzip"})
                    assert response.headers["content-encoding"] == "gzip"
                    assert "immutable" in response.headers["cache-control"]
                    assert client.get(base + asset, headers={"If-None-Match": response.headers["etag"]}).status_code == 304
                    assert client.get(base + "/api/labs", headers=headers).status_code == 200
                    assert client.get(base + "/api/labs").status_code == 401
                    assert client.get(base + "/api/labs", headers={**headers, "Origin": "https://foreign.example"}).status_code == 403
                    for path in ("/api/capture/stream", "/api/capture/stream/", "/api/capture/%73tream"):
                        blocked = client.post(base + path, json={}, headers={"X-Forwarded-For": "127.0.0.1"})
                        assert blocked.status_code == 403, (path, blocked.status_code)
                    archive = io.BytesIO()
                    with tarfile.open(fileobj=archive, mode="w") as tar:
                        info = tarfile.TarInfo("fixture.txt")
                        info.size = 256 * 1024
                        tar.addfile(info, io.BytesIO(b"x" * info.size))
                    content = archive.getvalue()
                    upload = client.post(base + "/api/images/uploads", headers=headers,
                        json={"name": "fixture.tar", "size": len(content), "kind": "archive"})
                    assert upload.status_code == 201, upload.text
                    url = base + "/api/images/uploads/" + upload.json()["id"]
                    sent = client.put(url, headers={**headers, "Content-Type": "application/octet-stream"},
                        content=(content[i:i+4096] for i in range(0, len(content), 4096)))
                    assert sent.status_code == 200, sent.text
                    assert client.delete(url, headers=headers).status_code == 200
                asyncio.run(check_websocket(base, context))
                result = {"http2": True, "gzip_cache_304": True, "auth_origin": True,
                          "streaming_upload": True, "websocket_origin": True, "pcap_proxy_blocked": True}
                if args.http3:
                    result["http3_gzip_bytes"] = asyncio.run(check_http3(tls_port, root_cert, asset, response.content))
                print(json.dumps(result))
            except Exception:
                log.flush()
                print((temp / "processes.log").read_text(), file=sys.stderr)
                raise
            finally:
                for process in reversed(processes):
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
