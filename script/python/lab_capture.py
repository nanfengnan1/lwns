"""One-use SSH capture tickets and bounded, server-owned tcpdump sessions."""
import asyncio
import copy
import os
import secrets
import shutil
import signal
import subprocess
import threading
import time
import uuid

from lab_core import LabError, stamp

LIVE = {"waiting", "ready", "starting", "running"}
TTL = 300
MAX_SESSIONS = 8
MAX_DURATION = 3600
PCAP_MAGIC = (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d")


class CaptureService:
    def __init__(self, manager, port=8090, spawn=None):
        self.manager, self.port = manager, port
        self.spawn = spawn or self.spawn_tcpdump
        self.sessions, self.tickets = {}, {}
        self.lock = threading.RLock()

    def capabilities(self):
        try:
            self.manager.authorize()
            if not shutil.which("tcpdump"):
                raise LabError("宿主机缺少 tcpdump，请安装后再抓包")
            return {"available": True, "error": "", "max_sessions": MAX_SESSIONS, "max_duration": MAX_DURATION}
        except LabError as exc:
            return {"available": False, "error": str(exc), "max_sessions": MAX_SESSIONS, "max_duration": MAX_DURATION}

    def prune(self):
        now = time.monotonic()
        for session in self.sessions.values():
            if session.state in ("waiting", "ready") and session.deadline <= now:
                session.state, session.error, session.finished_at = "expired", "连接凭证已过期，请重新开始抓包", stamp()
        self.tickets = {token: value for token, value in self.tickets.items() if value[1].state in LIVE and value[1].deadline > now}
        done = [key for key, s in self.sessions.items() if s.state not in LIVE]
        for key in done[:-50]:
            del self.sessions[key]

    def list(self, lab_id):
        self.manager.read(lab_id)
        with self.lock:
            self.prune()
            return [session.public() for session in reversed(list(self.sessions.values())) if session.target["lab"] == lab_id]

    def issue(self, lab_id, payload):
        self.manager.authorize()
        if not shutil.which("tcpdump") and self.spawn == self.spawn_tcpdump:
            raise LabError("宿主机缺少 tcpdump，请安装后再抓包")
        capture_filter, snaplen = payload.get("filter", ""), payload.get("snaplen", 0)
        if not isinstance(capture_filter, str) or len(capture_filter) > 1024 or any(ord(c) < 32 for c in capture_filter):
            raise LabError("抓包过滤条件不能包含控制字符或超过 1024 字符")
        if type(snaplen) is not int or not (snaplen == 0 or 64 <= snaplen <= 262144):
            raise LabError("抓包长度须为 0（完整）或 64–262144 字节")
        with self.manager.lock, self.lock:
            target = self.manager.capture_target(lab_id, payload.get("link"), payload.get("side", "a"))
            self.prune()
            if sum(s.state in LIVE for s in self.sessions.values()) >= MAX_SESSIONS:
                raise LabError("抓包会话已达上限（8），请先停止不用的会话")
            session = CaptureSession(self, target, capture_filter.strip(), snaplen)
            self.sessions[session.id] = session
            ticket = secrets.token_urlsafe(32)
            self.tickets[ticket] = ("launch", session)
            return {"session": session.public(), "ticket": ticket, "expires_in": TTL}

    def consume(self, ticket, kind):
        if not isinstance(ticket, str) or len(ticket) > 128:
            raise LabError("抓包凭证无效")
        with self.lock:
            self.prune()
            value = self.tickets.get(ticket)
            if not value or value[0] != kind:
                raise LabError("抓包凭证已过期、已使用或无效，请重新开始")
            del self.tickets[ticket]
            return value[1]

    def claim(self, ticket):
        session = self.consume(ticket, "launch")
        try:
            session.validate()
            with self.lock:
                if session.state != "waiting":
                    raise LabError("抓包会话已停止")
                session.state, session.deadline = "ready", time.monotonic() + TTL
                stream_ticket = secrets.token_urlsafe(32)
                self.tickets[stream_ticket] = ("stream", session)
                client_ticket = secrets.token_urlsafe(32)
                self.tickets[client_ticket] = ("client", session)
                return {"session": session.public(), "stream_ticket": stream_ticket, "client_ticket": client_ticket, "port": self.port}
        except Exception as exc:
            session.stop(str(exc), error=True)
            raise

    def client_report(self, payload):
        # A separate one-use ticket can only describe this launch, never start a
        # stream or address arbitrary local/server files. Paths are display data.
        status, path = payload.get("status"), payload.get("output_file", "")
        message = payload.get("error", "")
        if status not in ("launched", "error"):
            raise LabError("本地启动结果无效")
        for value, limit in ((path, 2048), (message, 1000)):
            if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
                raise LabError("本地启动结果包含无效文本")
        if type(payload.get("manual_auth", False)) is not bool:
            raise LabError("本地认证模式无效")
        session = self.consume(payload.get("ticket"), "client")
        with self.lock, session.lock:
            if session.state not in LIVE:
                raise LabError("抓包会话已结束")
            session.client = {"status": status, "output_file": path, "manual_auth": payload.get("manual_auth", False)}
            if status == "error" and session.state == "ready":
                session.state, session.error, session.finished_at = "error", message or "本地 Wireshark 启动失败，请重新配置后重试", stamp()
            return session.public()

    async def open(self, ticket):
        session = self.consume(ticket, "stream")
        try:
            await session.start()
            return session
        except BaseException as exc:
            await asyncio.shield(session.close(str(exc) or "抓包启动中断", error=True))
            raise

    async def close_lab(self, lab_id=None, session_id=None):
        with self.lock:
            selected = [s for s in self.sessions.values() if (lab_id is None or s.target["lab"] == lab_id)
                        and (session_id is None or s.id == session_id)]
        if session_id and not selected:
            raise LabError("抓包会话不存在")
        await asyncio.gather(*(s.close("抓包已停止") for s in selected))

    def spawn_tcpdump(self, session):
        target = session.target
        namespace = f'/proc/{target["pid"]}/ns/net'
        fd = os.open(namespace, os.O_RDONLY)
        try:
            session.validate()
            if os.fstat(fd).st_ino != os.stat(namespace).st_ino:
                raise LabError("容器网络命名空间已变化")
            args = ["nsenter", f"--net=/proc/self/fd/{fd}", "--", "tcpdump", "-i", target["port"],
                    "-U", "-s", str(session.snaplen), "-nn", "-w", "-", "--"]
            if session.filter:
                args.append(session.filter)
            return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    pass_fds=(fd,), start_new_session=True)
        finally:
            os.close(fd)


class CaptureSession:
    def __init__(self, service, target, capture_filter, snaplen):
        self.service, self.target, self.filter, self.snaplen = service, target, capture_filter, snaplen
        self.id, self.state = uuid.uuid4().hex, "waiting"
        self.created_at, self.started_at, self.finished_at = stamp(), None, None
        self.deadline = time.monotonic() + TTL
        self.error, self.logs, self.bytes = "", "", 0
        self.client = None
        self.process, self.monitor, self.stderr_thread = None, None, None
        self.closed, self.header = False, b""
        self.lock = threading.RLock()

    def public(self):
        with self.lock:
            return copy.deepcopy({"id": self.id, "lab": self.target["lab"], "link": self.target["link"], "side": self.target["side"],
                                  "label": self.target["label"], "state": self.state, "filter": self.filter, "snaplen": self.snaplen,
                                  "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
                                  "error": self.error, "logs": self.logs, "bytes": self.bytes, "client": self.client})

    def validate(self):
        t = self.target
        self.service.manager.capture_target(t["lab"], t["link"], t["side"], t)

    def read_errors(self):
        while value := self.process.stderr.read1(4096):
            with self.lock:
                self.logs = (self.logs + value.decode("utf-8", "replace"))[-16384:]

    def spawn(self):
        with self.service.manager.lock, self.lock:
            if self.closed or self.state != "ready":
                raise LabError("抓包会话已停止")
            self.validate()
            self.state = "starting"
            self.process = self.service.spawn(self)
            self.stderr_thread = threading.Thread(target=self.read_errors, name="capture-stderr-" + self.id, daemon=True)
            self.stderr_thread.start()

    async def start(self):
        await asyncio.to_thread(self.spawn)
        self.header = await asyncio.wait_for(asyncio.to_thread(self.process.stdout.read, 24), 10)
        if len(self.header) != 24 or self.header[:4] not in PCAP_MAGIC:
            await asyncio.to_thread(self.stderr_thread.join, 0.5)
            raise LabError(self.logs.strip() or "tcpdump 未返回有效的 PCAP 文件头")
        await asyncio.to_thread(self.validate)
        with self.lock:
            if self.closed:
                raise LabError("抓包会话已停止")
            self.state, self.started_at = "running", stamp()
        self.monitor = asyncio.create_task(self.watch())

    async def watch(self):
        started = time.monotonic()
        while not self.closed:
            await asyncio.sleep(3)
            if self.closed:
                return
            try:
                if time.monotonic() - started >= MAX_DURATION:
                    raise LabError("抓包达到 60 分钟上限，请重新开始")
                await asyncio.to_thread(self.validate)
            except Exception as exc:
                await self.close(str(exc), error=True)
                return

    async def stream(self):
        try:
            self.bytes += len(self.header)
            yield self.header
            while not self.closed:
                data = await asyncio.to_thread(self.process.stdout.read1, 65536)
                if not data:
                    if not self.closed:
                        code = await asyncio.to_thread(self.process.wait)
                        await asyncio.to_thread(self.stderr_thread.join, 0.5)
                        if code:
                            await self.close(self.logs.strip() or "tcpdump 异常退出", error=True)
                    break
                self.bytes += len(data)
                yield data
        finally:
            await asyncio.shield(self.close("抓包连接已结束"))

    def stop(self, reason, error=False):
        with self.lock:
            if self.closed or self.state not in LIVE:
                return
            self.closed, self.state = True, "error" if error else "stopped"
            self.error = reason if error else ""
            self.finished_at = stamp()
            proc = self.process
        if proc:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGINT)
                    proc.wait(timeout=2)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=3)
            if self.stderr_thread:
                self.stderr_thread.join(timeout=1)
            proc.stdout.close()
            proc.stderr.close()

    async def close(self, reason="抓包已停止", error=False):
        await asyncio.to_thread(self.stop, reason, error)
        monitor = self.monitor
        if monitor and monitor is not asyncio.current_task():
            self.monitor = None
            if not monitor.done():
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
