#!/usr/bin/env python3
"""Serve the Vue workbench, REST API and device terminals on one port."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from fastapi import FastAPI, Request, WebSocket
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse, Response
    import uvicorn
except ImportError:
    sys.exit("缺少后端依赖。请运行 python3 -m venv .venv，然后用 "
             ".venv/bin/python -m pip install -r script/python/requirements.txt 安装，"
             "使用 .venv/bin/python 启动后端。")

from lab_core import CATALOG, LabError, LabManager
from lab_terminal import TerminalService

ROOT = Path(__file__).resolve().parents[2]
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


def same_origin(connection, required=False):
    origin = connection.headers.get("origin")
    scheme = "https" if connection.url.scheme in ("https", "wss") else "http"
    return (not origin and not required) or origin == scheme + "://" + connection.headers.get("host", "")


def join_jobs():
    for thread in threading.enumerate():
        if thread.name.startswith("lab-job-"):
            thread.join()


def create_app(manager, token, web_dir=None, terminals=None):
    web_dir = Path(web_dir or ROOT / "web" / "dist").resolve()
    terminals = terminals or TerminalService(manager)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await terminals.close_lab()
        await asyncio.to_thread(join_jobs)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.terminals = terminals

    @app.websocket("/api/terminal")
    async def terminal(websocket: WebSocket):
        if not same_origin(websocket, required=True):
            await websocket.close(code=1008)
            return
        await terminals.connect(websocket)

    def dispatch(method, path, payload):
        # All filesystem and Docker operations run outside the ASGI event loop.
        if method == "GET" and (path in ("/", "/index.html") or path.startswith("/assets/")):
            relative = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            if "\\" in relative:
                return respond(404, {"error": "未找到"})
            candidate = (web_dir / relative).resolve()
            try:
                candidate.relative_to(web_dir)
            except ValueError:
                return respond(404, {"error": "未找到"})
            types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                     ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
                     ".woff": "font/woff", ".woff2": "font/woff2"}
            if relative == "index.html" and not candidate.is_file():
                return respond(503, "前端尚未构建。请在项目根目录运行：\n"
                                    "npm --prefix web ci\nnpm --prefix web run build\n")
            if candidate.suffix not in types or not candidate.is_file():
                return respond(404, {"error": "未找到"})
            return respond(200, candidate.read_bytes(), types[candidate.suffix])
        if method == "GET" and path == "/api/bootstrap":
            return respond(200, {"catalog": CATALOG, "environment": manager.environment(),
                                 "labs": manager.list_labs(),
                                 "example": json.loads((ROOT / "examples" / "basic-lab.json").read_text(encoding="utf-8"))})
        if method == "GET" and path == "/api/labs":
            return respond(200, manager.list_labs())
        if method == "GET" and path == "/api/environment":
            return respond(200, manager.environment())
        segments = path.strip("/").split("/")
        if len(segments) >= 3 and segments[:2] == ["api", "labs"]:
            lab_id = segments[2]
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
                if action in ("deploy", "destroy"):
                    return respond(202, manager.start_job(lab_id, action))
                if action == "exec":
                    return respond(200, manager.command(lab_id, payload.get("node"), payload.get("command")))
                if action == "terminals":
                    return respond(201, terminals.issue(lab_id, payload.get("node"), payload.get("mode", "default")))
        return respond(404, {"error": "未知 API"})

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def http(request: Request, path: str):
        path = "/" + path
        payload = {}
        try:
            if path.startswith("/api/"):
                expected = "Bearer " + token
                if not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
                    return respond(401, {"error": "请输入服务启动时显示的访问令牌"})
                if not same_origin(request):
                    return respond(403, {"error": "不接受跨站请求"})
                if request.method in ("POST", "PUT"):
                    if request.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise LabError("请求需要 application/json")
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 1024 * 1024:
                            raise LabError("请求超过 1 MiB")
                    try:
                        payload = json.loads(body)
                        if not isinstance(payload, dict):
                            raise ValueError()
                    except (ValueError, UnicodeError):
                        raise LabError("JSON 无效")
            result = await run_in_threadpool(dispatch, request.method, path, payload)
            segments = path.strip("/").split("/")
            if result.status_code == 202 and segments[-1] == "destroy":
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


def main():
    parser = argparse.ArgumentParser(description="route-ovs Docker / veth 工作台（Python 3.10+）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".route-ovs-labs")
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web" / "dist")
    parser.add_argument("--preview", action="store_true", help="仅编辑和保存拓扑")
    parser.add_argument("--docker-socket", default="/var/run/docker.sock")
    args = parser.parse_args()
    token = os.environ.get("ROUTE_OVS_TOKEN") or secrets.token_urlsafe(24)
    lock = acquire_lock(args.data_dir)
    try:
        manager = LabManager(args.data_dir, preview=args.preview, docker_socket=args.docker_socket)
        shown_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        print("Route OVS 工作台: http://{}:{}/#token={}".format(shown_host, args.port, token), flush=True)
        print("数据目录: " + str(manager.directory), flush=True)
        print("前端目录: " + str(args.web_dir), flush=True)
        print("访问令牌: " + token, flush=True)
        if args.preview:
            print("设计模式：部署和设备终端已禁用。", flush=True)
        # One process owns the deployment lock, jobs, tickets and terminal sessions.
        uvicorn.run(create_app(manager, token, args.web_dir), host=args.host, port=args.port,
                    ws="websockets-sansio", ws_max_size=65536, ws_max_queue=16,
                    timeout_graceful_shutdown=8, proxy_headers=False)
    finally:
        join_jobs()
        lock.close()


if __name__ == "__main__":
    try:
        main()
    except (LabError, OSError) as error:
        sys.exit(str(error))

