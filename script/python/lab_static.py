"""Static-only compression and caching; API and PCAP streams stay untouched."""
from pathlib import Path
import re

from starlette.exceptions import HTTPException
from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


def is_static_path(path):
    return path in ("/", "/index.html") or path.startswith("/assets/")


class StaticGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and is_static_path(scope["path"])
                and not any(name == b"range" for name, _ in scope["headers"])
                and accepts_gzip(Headers(scope=scope).get("accept-encoding", ""))):
            await super().__call__(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def accepts_gzip(value):
    for coding in value.lower().split(","):
        name, *parameters = coding.strip().split(";")
        if name.strip() != "gzip":
            continue
        quality = 1.0
        try:
            for parameter in parameters:
                key, _, amount = parameter.strip().partition("=")
                if key == "q":
                    quality = float(amount)
        except ValueError:
            return False
        return 0 < quality <= 1
    return False


class WorkbenchStatic:
    extensions = {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff", ".woff2"}
    fingerprint = re.compile(r"^/assets/[^/]+-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$")

    def __init__(self, directory, headers):
        self.files = StaticFiles(directory=directory, check_dir=False)
        self.headers = headers

    async def serve(self, request):
        path = request.url.path
        relative = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        if "\\" in relative or Path(relative).suffix not in self.extensions:
            return Response("未找到", status_code=404, headers=self.headers)
        try:
            # StaticFiles checks traversal/symlinks, streams files and implements
            # HEAD, ETag/Last-Modified revalidation and byte ranges.
            response = await self.files.get_response(relative, request.scope)
        except HTTPException as exc:
            missing_build = relative == "index.html" and exc.status_code == 404
            message = ("前端尚未构建。请在项目根目录运行：\n"
                       "npm --prefix web ci\nnpm --prefix web run build\n") if missing_build else "未找到"
            return Response(message, status_code=503 if missing_build else exc.status_code,
                            media_type="text/plain", headers=self.headers)
        response.headers.update(self.headers)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if self.fingerprint.fullmatch(path) else "no-cache")
        response.headers["Vary"] = "Accept-Encoding"
        if "etag" in response.headers:
            # gzip and identity have the same semantic content, not identical bytes.
            response.headers["ETag"] = "W/" + response.headers["ETag"].removeprefix("W/")
        return response
