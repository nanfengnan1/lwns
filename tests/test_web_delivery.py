"""Static delivery and reverse-proxy boundaries, without Docker mutations."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "script" / "python"))
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from lab_core import LabManager
from lab_server import create_app, proxy_address


class WebDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.web = self.root / "dist"
        (self.web / "assets").mkdir(parents=True)
        (self.web / "index.html").write_text("<html>workbench</html>", encoding="utf-8")
        self.script = b"const message = 'static gzip test';\n" * 4000
        (self.web / "assets/app-12345678.js").write_bytes(self.script)
        (self.web / "assets/plain.js").write_bytes(self.script)
        self.manager = LabManager(self.root / "labs", preview=True)
        self.app = create_app(self.manager, "secret", self.web)

    def tearDown(self):
        self.temp.cleanup()

    def test_gzip_identity_cache_and_revalidation(self):
        with TestClient(self.app) as client:
            response = client.get("/assets/app-12345678.js", headers={"Accept-Encoding": "gzip"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, self.script)
            self.assertEqual(response.headers["content-encoding"], "gzip")
            self.assertIn("immutable", response.headers["cache-control"])
            self.assertIn("Accept-Encoding", response.headers["vary"])
            etag = response.headers["etag"]
            self.assertTrue(etag.startswith("W/"))
            for encoding in ("identity", "gzip;q=0, identity", "br"):
                plain = client.get("/assets/app-12345678.js", headers={"Accept-Encoding": encoding})
                self.assertNotIn("content-encoding", plain.headers)
                self.assertEqual(plain.content, self.script)
                self.assertEqual(plain.headers["etag"], etag)
            unchanged = client.get("/assets/app-12345678.js", headers={"If-None-Match": etag})
            self.assertEqual(unchanged.status_code, 304)
            self.assertEqual(unchanged.content, b"")
            self.assertIn("immutable", unchanged.headers["cache-control"])
            self.assertIn("Accept-Encoding", unchanged.headers["vary"])

    def test_html_revalidates_and_discovers_new_build(self):
        with TestClient(self.app) as client:
            html = client.get("/")
            self.assertEqual(html.headers["cache-control"], "no-cache")
            self.assertEqual(client.get("/index.html", headers={"If-None-Match": html.headers["etag"]}).status_code, 304)
            (self.web / "index.html").write_text("<html>new build and changed chunks</html>", encoding="utf-8")
            changed = client.get("/", headers={"If-None-Match": html.headers["etag"]})
            self.assertEqual(changed.status_code, 200)
            self.assertIn("new build", changed.text)
            self.assertEqual(client.get("/assets/plain.js").headers["cache-control"], "no-cache")

    def test_head_range_missing_files_and_api_remain_uncached(self):
        with TestClient(self.app) as client:
            head = client.head("/assets/app-12345678.js")
            self.assertEqual(head.status_code, 200)
            self.assertEqual(head.content, b"")
            part = client.get("/assets/app-12345678.js", headers={"Range": "bytes=0-9", "Accept-Encoding": "gzip"})
            self.assertEqual(part.status_code, 206)
            self.assertEqual(part.content, self.script[:10])
            self.assertNotIn("content-encoding", part.headers)
            for path in ("/assets/missing-12345678.js", "/script/python/lab_server.py", "/assets/%2e%2e/%2e%2e/secret.js"):
                response = client.get(path)
                self.assertEqual(response.status_code, 404, path)
                self.assertEqual(response.headers["cache-control"], "no-store")
            api = client.get("/api/labs", headers={"Authorization": "Bearer secret"})
            self.assertEqual(api.status_code, 200)
            self.assertEqual(api.headers["cache-control"], "no-store")
            self.assertNotIn("content-encoding", api.headers)
            (self.web / "index.html").unlink()
            self.assertEqual(client.get("/").status_code, 503)

    def test_symlinks_cannot_escape_static_root(self):
        secret = self.root / "secret.js"
        secret.write_text("secret", encoding="utf-8")
        try:
            (self.web / "assets/leak-12345678.js").symlink_to(secret)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with TestClient(self.app) as client:
            self.assertEqual(client.get("/assets/leak-12345678.js").status_code, 404)

    def test_proxy_origin_auth_and_forwarded_client_for_capture(self):
        proxy = ProxyHeadersMiddleware(self.app, trusted_hosts=["127.0.0.1"])
        headers = {"Host": "lab.example:8443", "Origin": "https://lab.example:8443",
                   "X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.10",
                   "Authorization": "Bearer secret"}
        with TestClient(proxy, client=("127.0.0.1", 12345)) as client:
            self.assertEqual(client.get("/api/labs", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/labs", headers={**headers, "Origin": "https://foreign.example"}).status_code, 403)
            self.assertEqual(client.get("/api/labs", headers={**headers, "Authorization": "Bearer wrong"}).status_code, 401)
            self.assertEqual(client.post("/api/capture/stream", headers=headers, json={}).status_code, 403)
            with client.websocket_connect("/api/terminal", headers=headers) as ws:
                ws.send_json({"type": "connect", "ticket": "invalid", "cols": 80, "rows": 24})
                self.assertEqual(ws.receive_json()["type"], "error")
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect("/api/terminal", headers={**headers, "Origin": "https://foreign.example"}):
                    pass
        for app in (proxy, self.app):
            with TestClient(app, client=("192.0.2.10", 12345)) as client:
                self.assertEqual(client.get("/api/labs", headers=headers).status_code, 403)

    def test_proxy_option_requires_explicit_address(self):
        for value in ("127.0.0.1", "::1", "192.0.2.0/24"):
            self.assertEqual(proxy_address(value), value)
        self.assertEqual(proxy_address("192.0.2.10/24"), "192.0.2.0/24")
        for value in ("*", "", "localhost", "127.0.0.1,::1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                proxy_address(value)


if __name__ == "__main__":
    unittest.main()
