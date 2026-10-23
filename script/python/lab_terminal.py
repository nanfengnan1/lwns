"""Bounded WebSocket / Linux PTY sessions for owned Docker devices."""
import asyncio
from contextlib import suppress
import errno
import logging
import os
import secrets
import signal
import threading
import time

from starlette.websockets import WebSocketDisconnect
from lab_core import LabError

log = logging.getLogger(__name__)

# Docker CLI exit alone does not terminate the exec process inside the container.
# Only processes carrying this session's random environment marker are reaped.
# The cleanup exec itself does not receive that environment variable.
CLEANUP = r'''
for pass in HUP KILL; do
  for entry in /proc/[0-9]*/environ; do
    [ -r "$entry" ] || continue
    if tr '\000' '\n' < "$entry" 2>/dev/null | grep -Fqx "ROUTE_OVS_TERMINAL=$1"; then
      pid=${entry#/proc/}; pid=${pid%/environ}
      [ "$pid" -gt 1 ] && kill -"$pass" "$pid" 2>/dev/null
    fi
  done
  [ "$pass" = HUP ] && sleep 0.1
done
exit 0
'''


def dimensions(cols, rows):
    if type(cols) is not int or type(rows) is not int or not 2 <= cols <= 1000 or not 1 <= rows <= 500:
        raise LabError("终端尺寸无效")
    return cols, rows


class TerminalService:
    def __init__(self, manager, session_factory=None):
        self.manager = manager
        self.tickets = {}
        self.ticket_lock = threading.Lock()
        self.sessions = set()  # Accessed only by the ASGI event loop.
        self.session_factory = session_factory or TerminalSession

    def issue(self, lab_id, node, mode):
        self.manager.authorize()
        target = self.manager.terminal_target(lab_id, node, mode)
        with self.ticket_lock:
            now = time.monotonic()
            self.tickets = {key: value for key, value in self.tickets.items() if value[0] > now}
            if len(self.tickets) >= 128:
                raise LabError("待连接终端过多，请稍后重试")
            ticket = secrets.token_urlsafe(32)
            self.tickets[ticket] = (now + 30, target)
        return {"ticket": ticket, "expires_in": 30}

    def consume(self, ticket):
        if not isinstance(ticket, str) or len(ticket) > 128:
            raise LabError("终端连接凭证无效")
        with self.ticket_lock:
            entry = self.tickets.pop(ticket, None)
        if entry is None or entry[0] <= time.monotonic():
            raise LabError("终端连接凭证已过期或已使用，请重新连接")
        return entry[1]

    async def connect(self, websocket):
        session = None
        await websocket.accept()
        try:
            hello = await asyncio.wait_for(websocket.receive_json(), 5)
            if not isinstance(hello, dict) or hello.get("type") != "connect":
                raise LabError("需要终端连接凭证")
            target = self.consume(hello.get("ticket"))
            cols, rows = dimensions(hello.get("cols", 80), hello.get("rows", 24))
            if len(self.sessions) >= 32:
                raise LabError("终端会话已达上限（32），请先关闭不用的标签")
            session = self.session_factory(self.manager, target, websocket)
            self.sessions.add(session)
            await session.run(cols, rows)
        except (LabError, ValueError, asyncio.TimeoutError) as exc:
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await websocket.send_json({"type": "error", "message": str(exc) or "终端连接超时"})
        except (WebSocketDisconnect, OSError):
            pass
        except Exception:
            log.exception("Terminal connection failed")
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await websocket.send_json({"type": "error", "message": "终端连接失败，请查看后端日志"})
        finally:
            if session:
                await asyncio.shield(session.close())
                self.sessions.discard(session)
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await websocket.close()

    async def close_lab(self, lab_id=None):
        with self.ticket_lock:
            self.tickets = {key: value for key, value in self.tickets.items()
                            if lab_id is not None and value[1]["lab"] != lab_id}
        await asyncio.gather(*(s.close() for s in list(self.sessions)
                               if lab_id is None or s.target["lab"] == lab_id))


class TerminalSession:
    def __init__(self, manager, target, websocket):
        self.manager, self.target, self.websocket = manager, target, websocket
        self.marker = secrets.token_hex(24)
        self.master = None
        self.process = None
        self.tasks = []
        self.closed = False
        self.close_lock = asyncio.Lock()
        self.ack = asyncio.Event()
        self.input_queue = asyncio.Queue(maxsize=16)

    async def validate(self):
        await asyncio.to_thread(self.manager.terminal_target, self.target["lab"], self.target["node"],
                                self.target["mode"], self.target)

    async def run(self, cols, rows):
        async with self.close_lock:
            await self.start(cols, rows)
        if self.closed:
            return
        self.tasks = [asyncio.create_task(self.output()), asyncio.create_task(self.input()),
                      asyncio.create_task(self.write_input()), asyncio.create_task(self.monitor())]
        done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if not task.cancelled():
                task.result()

    async def start(self, cols, rows):
        # Import Unix-only modules lazily so Windows design mode remains usable.
        import pty
        import tty
        await self.validate()
        if self.closed:
            return
        self.master, slave = pty.openpty()
        try:
            tty.setraw(slave)
            os.set_blocking(self.master, False)
            self.resize(cols, rows)
            program = ["vtysh"] if self.target["program"] == "vtysh" else ["sh", "-i"]
            argv = self.manager.docker + ["exec", "-it", "-u", "0", "-e", "TERM=xterm-256color",
                                          "-e", "ROUTE_OVS_TERMINAL=" + self.marker,
                                          self.target["container"]] + program
            self.process = await asyncio.create_subprocess_exec(
                *argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        finally:
            os.close(slave)
        # Re-check after process creation as cleanup may have started concurrently.
        await self.validate()
        await self.websocket.send_json({"type": "ready", "program": self.target["program"]})

    async def ready_fd(self, write=False):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        fd = self.master
        if fd is None:
            raise OSError("Terminal closed")
        def ready():
            if not future.done():
                future.set_result(None)
        add = loop.add_writer if write else loop.add_reader
        remove = loop.remove_writer if write else loop.remove_reader
        add(fd, ready)
        try:
            await future
        finally:
            remove(fd)

    async def output(self):
        while not self.closed:
            await self.ready_fd()
            try:
                data = os.read(self.master, 16384)
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                data = b""
            if not data:
                code = await self.process.wait()
                await self.websocket.send_json({"type": "exit", "code": code})
                return
            # Wait for xterm's write callback before reading the next chunk.
            # This bounds output even if the browser renders slowly.
            self.ack.clear()
            await asyncio.wait_for(self.websocket.send_bytes(data), 30)
            await asyncio.wait_for(self.ack.wait(), 30)

    async def input(self):
        while not self.closed:
            message = await self.websocket.receive_json()
            if not isinstance(message, dict):
                raise LabError("终端消息无效")
            kind = message.get("type")
            if kind == "ack":
                self.ack.set()
            elif kind == "resize":
                self.resize(*dimensions(message.get("cols"), message.get("rows")))
            elif kind == "input":
                data = message.get("data")
                if not isinstance(data, str) or len(data) > 16384:
                    raise LabError("终端输入过长")
                encoded = data.encode("utf-8")
                if len(encoded) > 16384:
                    raise LabError("终端输入过长")
                try:
                    self.input_queue.put_nowait(encoded)
                except asyncio.QueueFull:
                    raise LabError("终端输入过快，请重新连接并分批粘贴")
            else:
                raise LabError("未知终端消息")

    async def write_input(self):
        # A busy PTY must not prevent the reader from processing output ACKs.
        while not self.closed:
            remaining = memoryview(await self.input_queue.get())
            while remaining and not self.closed:
                try:
                    remaining = remaining[os.write(self.master, remaining):]
                except BlockingIOError:
                    await self.ready_fd(write=True)

    def resize(self, cols, rows):
        import fcntl
        import struct
        import termios
        if self.master is not None:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            if self.process and self.process.returncode is None:
                with suppress(ProcessLookupError):
                    self.process.send_signal(signal.SIGWINCH)

    async def monitor(self):
        while not self.closed:
            await asyncio.sleep(3)
            await self.validate()

    async def close(self):
        async with self.close_lock:
            if self.closed:
                return
            self.closed = True
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            if self.process:
                if self.process.returncode is None:
                    with suppress(ProcessLookupError):
                        self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), 1)
                    except asyncio.TimeoutError:
                        with suppress(ProcessLookupError):
                            self.process.kill()
                        await self.process.wait()
                # Container IDs are immutable; never substitute a name on cleanup.
                try:
                    await asyncio.to_thread(self.manager.runner, self.manager.docker + [
                        "exec", "-u", "0", self.target["container"], "sh", "-c", CLEANUP,
                        "terminal-cleanup", self.marker], timeout=5, check=False)
                except LabError as exc:
                    log.warning("Terminal cleanup: %s", exc)
            if self.master is not None:
                os.close(self.master)
                self.master = None
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await self.websocket.close()
