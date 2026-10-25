#!/usr/bin/env python3
"""Serve the Vue workbench, REST API and device terminals on one port."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import ipaddress
import io
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
if __name__ == "__main__" and sys.argv[1:2] == ["device"]:
    from lab_device_cli import main as device_main
    sys.exit(device_main(sys.argv[2:]))

try:
    from fastapi import FastAPI, Request, WebSocket
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
    import uvicorn
except ImportError:
    sys.exit("缺少后端依赖。请运行 python3 -m venv .venv，然后用 "
             ".venv/bin/python -m pip install -r script/python/requirements.txt 安装，"
             "使用 .venv/bin/python 启动后端。")

from lab_core import CATALOG, LabError, LabManager
from lab_terminal import TerminalService
from lab_images import ImageService, MAX_UPLOAD
from lab_device_service import DevicePackageService
from lab_capture import CaptureService
from lab_static import StaticGZipMiddleware, WorkbenchStatic, is_static_path
from lab_paths import default_data_dir, resource_root

ROOT = resource_root()
log = logging.getLogger(__name__)
HEADERS = {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; connect-src 'self' ws: wss:; "
                               "frame-ancestors 'none'; base-uri 'none'",
}


def respond(code, content, mime=None):
    if isinstance(content, (dict, list)):
        return JSONResponse(content, status_code=code, headers=HEADERS)
    return Response(content, status_code=code, media_type=mime or "text/plain", headers=HEADERS)


def origin_key(value):
    """Compare URL origins, including implicit default ports, not raw strings."""
    if not value or any(character.isspace() for character in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def same_origin(connection, required=False):
    origin = connection.headers.get("origin")
    if origin is None:
        return not required
    # Only Uvicorn's explicitly trusted proxy middleware may change the scheme.
    # Never trust arbitrary X-Forwarded-* headers here.
    scheme = "https" if connection.url.scheme in ("https", "wss") else "http"
    expected = origin_key(scheme + "://" + connection.headers.get("host", ""))
    return expected is not None and origin_key(origin) == expected


def join_jobs():
    for thread in threading.enumerate():
        if thread.name.startswith(("lab-job-", "lab-update-")):
            thread.join()


def create_app(manager, token, web_dir=None, terminals=None, images=None, captures=None, capture_port=8090, device_packages=None):
    web_dir = Path(web_dir or ROOT / "web" / "dist").resolve()
    terminals = terminals or TerminalService(manager)
    images = images or ImageService(manager)
    device_packages = device_packages or DevicePackageService(manager, images=images, max_upload=images.max_upload)
    captures = captures or CaptureService(manager, port=capture_port)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await captures.close_lab()
        await terminals.close_lab()
        await asyncio.to_thread(join_jobs)
        await asyncio.to_thread(images.wait)
        await asyncio.to_thread(device_packages.wait)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(StaticGZipMiddleware, minimum_size=1024, compresslevel=6)
    static = WorkbenchStatic(web_dir, HEADERS)
    app.state.terminals = terminals
    app.state.images = images
    app.state.device_packages = device_packages
    app.state.captures = captures

    async def capture_payload(request, full=False):
        if not same_origin(request) or request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise LabError("抓包连接需要同源 JSON 请求")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 4096:
                raise LabError("抓包连接请求过大")
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError()
            return payload if full else payload.get("ticket")
        except (ValueError, UnicodeError):
            raise LabError("抓包连接 JSON 无效")

    @app.post("/api/capture/claim")
    async def claim_capture(request: Request):
        # A native launcher redeems this narrow, one-use ticket, never the Web token.
        try:
            ticket = await capture_payload(request)
            return respond(200, await run_in_threadpool(captures.claim, ticket))
        except LabError as exc:
            return respond(400, {"error": str(exc)})

    @app.post("/api/capture/client-report")
    async def report_capture_client(request: Request):
        try:
            payload = await capture_payload(request, full=True)
            return respond(200, await run_in_threadpool(captures.client_report, payload))
        except LabError as exc:
            return respond(400, {"error": str(exc)})

    @app.post("/api/capture/stream")
    async def stream_capture(request: Request):
        try:
            peer = ipaddress.ip_address(request.client.host) if request.client else None
            if not peer or not (peer.is_loopback or (getattr(peer, "ipv4_mapped", None) and peer.ipv4_mapped.is_loopback)):
                return respond(403, {"error": "抓包数据只允许宿主机回环连接，请通过 SSH 转发"})
            ticket = await capture_payload(request)
            session = await captures.open(ticket)
            return StreamingResponse(session.stream(), media_type="application/vnd.tcpdump.pcap",
                                     headers={**HEADERS, "X-Accel-Buffering": "no"})
        except (LabError, ValueError, asyncio.TimeoutError) as exc:
            return respond(400, {"error": str(exc) or "抓包启动超时"})

    @app.websocket("/api/terminal")
    async def terminal(websocket: WebSocket):
        if not same_origin(websocket, required=True):
            await websocket.close(code=1008)
            return
        await terminals.connect(websocket)

    def dispatch(method, path, payload):
        # All filesystem and Docker operations run outside the ASGI event loop.
        segments = path.strip("/").split("/")
        if method == "GET" and path == "/api/bootstrap":
            images.snapshot(refresh=True)
            device_packages.snapshot(refresh=True)
            return respond(200, {"catalog": images.catalog() + device_packages.catalog(), "environment": manager.environment(),
                                 "labs": manager.list_labs()})
        if method == "GET" and path == "/api/labs":
            return respond(200, manager.list_labs())
        if method == "POST" and path == "/api/labs":
            if set(payload) != {"name"}:
                raise LabError("新建项目只接受项目名称 name")
            return respond(201, manager.create_project(payload["name"]))
        if method == "GET" and path == "/api/environment":
            return respond(200, manager.environment())
        if method == "GET" and path == "/api/capture/capabilities":
            return respond(200, captures.capabilities())
        if method == "GET" and path == "/api/capture/client":
            output = io.BytesIO()
            folder = ROOT / "clients" / "capture"
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in ("launcher.py", "remote_relay.py", "configure.ps1", "install.ps1", "install.sh", "README.md"):
                    archive.write(folder / name, name)
                if (folder / "dist" / "route-ovs-capture.exe").is_file():
                    archive.write(folder / "dist" / "route-ovs-capture.exe", "route-ovs-capture.exe")
            return Response(output.getvalue(), media_type="application/zip", headers={**HEADERS, "Content-Disposition": 'attachment; filename="route-ovs-capture-client.zip"'})
        if method == "GET" and path == "/api/catalog":
            device_packages.snapshot(refresh=True)
            return respond(200, images.catalog() + device_packages.catalog())
        if path == "/api/device-packages" and method == "GET":
            return respond(200, device_packages.snapshot())
        if path == "/api/device-packages/refresh" and method == "POST":
            return respond(200, device_packages.snapshot(refresh=True))
        if path == "/api/device-packages/uploads" and method == "POST":
            return respond(201, device_packages.create_upload(payload))
        if path == "/api/device-packages/inspect" and method == "POST":
            return respond(200, device_packages.inspect_upload(payload))
        if path == "/api/device-packages/jobs" and method == "POST":
            return respond(202, device_packages.start(payload))
        if segments[:2] == ["api", "device-packages"]:
            if len(segments) == 4 and segments[2] == "uploads" and method == "DELETE":
                device_packages.discard_upload(segments[3])
                return respond(200, {"ok": True})
            if len(segments) == 4 and segments[2] == "artifacts" and method in ("GET", "HEAD"):
                artifact, filename = device_packages.artifact(segments[3])
                return FileResponse(artifact, filename=filename, media_type="application/zip", headers=HEADERS)
            if len(segments) == 3 and method == "PATCH":
                return respond(200, device_packages.rename(segments[2], payload))
            if len(segments) == 3 and method == "DELETE":
                device_packages.remove(segments[2])
                return respond(200, {"ok": True})
        if path == "/api/images":
            if method == "GET":
                return respond(200, images.snapshot())
        if path == "/api/images/refresh" and method == "POST":
            return respond(200, images.snapshot(refresh=True))
        if path == "/api/images/jobs" and method == "POST":
            return respond(202, images.start(payload))
        if path == "/api/images/uploads" and method == "POST":
            return respond(201, images.create_upload(payload))
        if len(segments) == 3 and segments[:2] == ["api", "images"]:
            if method == "PUT":
                return respond(200, images.update(segments[2], payload))
            if method == "DELETE":
                return respond(202, images.start({"mode": "delete", "id": segments[2]}))
        if len(segments) == 4 and segments[:3] == ["api", "images", "uploads"] and method == "DELETE":
            images.discard_upload(segments[3])
            return respond(200, {"ok": True})
        if len(segments) >= 3 and segments[:2] == ["api", "labs"]:
            lab_id = segments[2]
            if len(segments) == 4 and segments[3] == "captures":
                if method == "GET":
                    return respond(200, captures.list(lab_id))
                if method == "POST":
                    return respond(201, captures.issue(lab_id, payload))
            if len(segments) == 3:
                if method == "GET":
                    return respond(200, manager.status(lab_id))
                if method == "PUT":
                    if payload.get("id") != lab_id:
                        raise LabError("URL 与拓扑 ID 不一致")
                    return respond(200, manager.save(payload))
                if method == "DELETE":
                    manager.delete(lab_id)
                    return respond(200, {"ok": True})
            if len(segments) == 4 and method == "POST":
                action = segments[3]
                if action in ("open", "close"):
                    if payload:
                        raise LabError("打开和关闭项目需要空 JSON 对象")
                    if action == "open":
                        return respond(200, manager.status(lab_id))
                    manager.close_project(lab_id)
                    return respond(200, {"ok": True, "id": lab_id})
                if action == "save":
                    if set(payload) != {"topology"}:
                        raise LabError("保存项目只接受 topology")
                    topology = payload["topology"]
                    if not isinstance(topology, dict) or topology.get("id") != lab_id:
                        raise LabError("URL 与拓扑 ID 不一致")
                    return respond(200, manager.save_project(topology))
                if action == "layout":
                    return respond(200, manager.save_layout(lab_id, payload))
                if action == "rename":
                    if set(payload) != {"name"}:
                        raise LabError("重命名只接受项目名称 name")
                    return respond(200, manager.rename(lab_id, payload["name"]))
                if action == "configs":
                    return respond(200, manager.save_configs(lab_id, payload.get("node")))
                if action == "update":
                    return respond(202, manager.start_update(lab_id, payload))
                if action in ("deploy", "destroy"):
                    return respond(202, manager.start_job(lab_id, action))
                if action == "exec":
                    return respond(200, manager.command(lab_id, payload.get("node"), payload.get("command")))
                if action == "terminals":
                    return respond(201, terminals.issue(lab_id, payload.get("node"), payload.get("mode", "default")))
            if method == "GET" and len(segments) in (4, 5) and segments[3] == "configs":
                return respond(200, manager.configs(lab_id, segments[4] if len(segments) == 5 else None))
        return respond(404, {"error": "未知 API"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
    async def http(request: Request, path: str):
        path = "/" + path
        payload = {}
        try:
            if is_static_path(path) and request.method in ("GET", "HEAD"):
                return await static.serve(request)
            if path.startswith("/api/"):
                expected = "Bearer " + token
                if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
                    return respond(401, {"error": "请输入服务启动时显示的访问令牌"})
                if not same_origin(request):
                    return respond(403, {"error": "不接受跨站请求"})
                segments = path.strip("/").split("/")
                if (request.method == "PUT" and len(segments) == 4
                        and segments[0] == "api" and segments[1] in ("images", "device-packages") and segments[2] == "uploads"):
                    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
                        raise LabError("文件上传需要 application/octet-stream")
                    upload_id = segments[3]
                    upload_service = images if segments[1] == "images" else device_packages
                    info = await run_in_threadpool(upload_service.begin_upload, upload_id)
                    stream, complete, size = None, False, 0
                    try:
                        stream = await run_in_threadpool((upload_service.upload_path(upload_id) / "data").open, "xb")
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > info["size"] or size > upload_service.max_upload:
                                raise LabError("上传数据超过声明的文件大小")
                            await run_in_threadpool(stream.write, chunk)
                        await run_in_threadpool(stream.close)
                        result = await run_in_threadpool(upload_service.finish_upload, upload_id, size)
                        complete = True
                        return respond(200, result)
                    finally:
                        if stream and not stream.closed:
                            await run_in_threadpool(stream.close)
                        if not complete:
                            await run_in_threadpool(upload_service.discard_upload, upload_id, True)
                if request.method in ("POST", "PUT", "PATCH"):
                    if request.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise LabError("请求需要 application/json")
                    body = bytearray()
                    # Updates include both the edited topology and its base snapshot.
                    limit = 2 * 1024 * 1024 if len(segments) == 4 and segments[:2] == ["api", "labs"] and segments[3] == "update" else 1024 * 1024
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > limit:
                            raise LabError(f"请求超过 {limit // (1024 * 1024)} MiB")
                    try:
                        payload = json.loads(body)
                        if not isinstance(payload, dict):
                            raise ValueError()
                    except (ValueError, UnicodeError):
                        raise LabError("JSON 无效")
            segments = path.strip("/").split("/")
            if request.method == "DELETE" and len(segments) == 5 and segments[:2] == ["api", "labs"] and segments[3] == "captures":
                await captures.close_lab(segments[2], segments[4])
                return respond(200, {"ok": True})
            result = await run_in_threadpool(dispatch, request.method, path, payload)
            if result.status_code == 202 and segments[-1] in ("destroy", "update"):
                await captures.close_lab(segments[2])
                await terminals.close_lab(segments[2])
            if (result.status_code == 200 and request.method == "POST"
                    and len(segments) == 4 and segments[:2] == ["api", "labs"] and segments[3] == "close"):
                await captures.close_lab(segments[2])
                await terminals.close_lab(segments[2])
            return result
        except LabError as exc:
            return respond(400, {"error": str(exc)})
        except Exception:
            log.exception("API request failed")
            return respond(500, {"error": "服务处理失败，请查看后端日志"})

    return app


def acquire_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / ".server.lock").open("a+b")
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise LabError("该数据目录已被另一个后端占用")
    return stream


def proxy_address(value):
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise argparse.ArgumentTypeError("--trusted-proxy 需要明确的代理 IP/CIDR，不接受 *")
    return str(network) if "/" in value else value


def main():
    parser = argparse.ArgumentParser(description="route-ovs Docker / veth 工作台（Python 3.10+）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web" / "dist")
    parser.add_argument("--preview", action="store_true", help="仅编辑和保存拓扑")
    parser.add_argument("--docker-socket", default="/var/run/docker.sock")
    parser.add_argument("--max-image-upload-gib", type=int, default=MAX_UPLOAD // (1024 ** 3))
    parser.add_argument("--trusted-proxy", action="append", type=proxy_address, default=[],
                        help="可信反向代理的 IP/CIDR，可重复指定；默认不信任代理头")
    args = parser.parse_args()
    if args.max_image_upload_gib < 1:
        parser.error("--max-image-upload-gib 必须大于 0")
    token = os.environ.get("ROUTE_OVS_TOKEN") or secrets.token_urlsafe(24)
    lock = acquire_lock(args.data_dir)
    try:
        manager = LabManager(args.data_dir, preview=args.preview, docker_socket=args.docker_socket)
        images = ImageService(manager, max_upload=args.max_image_upload_gib * 1024 ** 3)
        shown_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        print("Route OVS 工作台: http://{}:{}/#token={}".format(shown_host, args.port, token), flush=True)
        print("数据目录: " + str(manager.directory), flush=True)
        print("前端目录: " + str(args.web_dir), flush=True)
        print("访问令牌: " + token, flush=True)
        if args.preview:
            print("设计模式：部署和设备终端已禁用。", flush=True)
        # One process owns the deployment lock, jobs, tickets and terminal sessions.
        uvicorn.run(create_app(manager, token, args.web_dir, images=images, capture_port=args.port), host=args.host, port=args.port,
                    ws="websockets-sansio", ws_max_size=65536, ws_max_queue=16,
                    timeout_graceful_shutdown=8, proxy_headers=bool(args.trusted_proxy),
                    forwarded_allow_ips=args.trusted_proxy)
    finally:
        join_jobs()
        if "images" in locals():
            images.wait()
        lock.close()


if __name__ == "__main__":
    try:
        main()
    except (LabError, OSError) as error:
        sys.exit(str(error))

