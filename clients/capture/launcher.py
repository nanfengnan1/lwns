#!/usr/bin/env python3
"""Native route-ovs URL handler. SSH credentials remain in local Wireshark."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def config_path():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) if os.name == "nt" else Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "route-ovs" / "capture-client.json"


def default_capture_dir():
    return str(Path.home() / "route-ovs" / "captures")


def diagnostic(message):
    path = config_path().with_name("capture-launcher.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 128 * 1024:
        path.write_text("", encoding="utf-8")
    with path.open("a", encoding="utf-8") as output:
        output.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    return path


def origin(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("后端地址须为 http(s)://主机:端口，不包含路径或凭据")
    if any(ord(c) <= 32 for c in value) or parsed.port == 0:
        raise ValueError("后端地址无效")
    return parsed.scheme + "://" + parsed.netloc.lower()


def parse_uri(value):
    if len(value) > 4096:
        raise ValueError("抓包链接过长")
    parsed = urlsplit(value)
    if parsed.scheme != "route-ovs" or parsed.netloc not in ("capture", "configure") or parsed.path not in ("", "/") or parsed.fragment:
        raise ValueError("不支持的抓包链接")
    fields = parse_qs(parsed.query, strict_parsing=True)
    expected = {"server", "ticket"} if parsed.netloc == "capture" else {"server"}
    if set(fields) != expected or any(len(v) != 1 for v in fields.values()):
        raise ValueError("抓包链接参数无效")
    if parsed.netloc == "configure":
        return origin(fields["server"][0]), None
    ticket = fields["ticket"][0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", ticket):
        raise ValueError("抓包启动凭证无效")
    return origin(fields["server"][0]), ticket


def load_config(path):
    if not path.exists():
        return {"version": 1, "connections": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("connections"), dict):
        raise ValueError("本地抓包配置无效：" + str(path))
    return data


def save_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def default_wireshark():
    if result := shutil.which("wireshark"):
        return result
    if os.name == "nt":
        for folder in (os.environ.get("ProgramFiles", "C:/Program Files"), os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")):
            candidate = Path(folder) / "Wireshark" / "Wireshark.exe"
            if candidate.is_file():
                return str(candidate)
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Wireshark.exe") as key:
                return winreg.QueryValue(key, None)
        except OSError:
            pass
    return ""


def validate_connection(value):
    keys = ("wireshark", "host", "port", "username", "profile", "sshkey", "autostart", "capture_dir")
    result = {key: value.get(key, "") for key in keys}
    result["capture_dir"] = value.get("capture_dir") or default_capture_dir()
    for key in ("wireshark", "host", "username", "profile", "sshkey", "capture_dir"):
        if not isinstance(result[key], str) or any(ord(c) < 32 for c in result[key]):
            raise ValueError("本地连接配置无效：" + key)
        result[key] = result[key].strip()
    result["port"] = int(result["port"])
    if not 1 <= result["port"] <= 65535 or not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,253}", result["host"]):
        raise ValueError("SSH 主机或端口无效")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", result["username"]):
        raise ValueError("请填写 SSH 用户名")
    if any(c in result["profile"] for c in "/\\") or result["profile"] in (".", ".."):
        raise ValueError("Wireshark Profile 名称无效")
    executable = Path(result["wireshark"]).expanduser()
    if not executable.is_file() or executable.name.lower() not in ("wireshark", "wireshark.exe"):
        raise ValueError("请选择图形程序 Wireshark.exe / wireshark，不能使用无界面的 tshark")
    result["wireshark"] = str(executable.resolve())
    if result["sshkey"]:
        keyfile = Path(result["sshkey"]).expanduser()
        if not keyfile.is_file():
            raise ValueError("SSH 私钥文件不存在")
        result["sshkey"] = str(keyfile.resolve())
    result["autostart"] = result["autostart"] is True
    directory = Path(result["capture_dir"]).expanduser()
    if not directory.is_absolute():
        raise ValueError("抓包保存目录需要使用本机绝对路径")
    result["capture_dir"] = str(directory)
    return result


def configure(server, previous=None, terminal=False):
    defaults = {"server": server, "wireshark": default_wireshark(), "host": urlsplit(server).hostname, "port": 22,
                "username": "", "profile": "", "sshkey": "", "autostart": False, "capture_dir": default_capture_dir(), **(previous or {})}
    if terminal:
        print("配置受信任的抓包后端：" + server)
        print("SSH 密码/密钥口令在本机 Wireshark 的 SSH 接口配置中输入，本启动器不保存密码。")
        for key, label in (("wireshark", "Wireshark 路径"), ("host", "SSH 主机"), ("port", "SSH 端口"), ("username", "SSH 用户名"), ("profile", "已有 Wireshark Profile（可空）"), ("sshkey", "私钥路径（可空，密码认证不需要）"), ("capture_dir", "本机抓包保存目录")):
            value = input(f'{label} [{defaults[key]}]: ').strip()
            if value:
                defaults[key] = value
        defaults["autostart"] = input("认证已配置好，自动开始抓包？[y/N]: ").lower() == "y"
    elif os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="route-ovs-setup-") as folder:
            source, output = Path(folder) / "input.json", Path(folder) / "output.json"
            source.write_text(json.dumps(defaults, ensure_ascii=True), encoding="utf-8")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "configure.ps1"),
                                     "-InputPath", str(source), "-OutputPath", str(output)], creationflags=CREATE_NO_WINDOW)
            if result.returncode or not output.exists():
                raise ValueError("本地连接配置已取消")
            defaults = json.loads(output.read_text(encoding="utf-8-sig"))
    else:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            raise ValueError("请安装 python3-tk，或在终端运行 launcher.py --configure 后端地址 --terminal") from exc
        window = tk.Tk(); window.title("route-ovs SSH 抓包连接")
        frame = ttk.Frame(window, padding=20); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="仅为你信任的工作台配置 SSH 连接：\n" + server, wraplength=520).grid(row=0, column=0, columnspan=2, sticky="w", pady=8)
        fields = {}
        for row, (key, title) in enumerate((("wireshark", "Wireshark 路径"), ("host", "SSH 主机"), ("port", "SSH 端口"), ("username", "SSH 用户名"), ("profile", "Wireshark Profile"), ("sshkey", "私钥路径（可选）"), ("capture_dir", "本机保存目录")), 1):
            ttk.Label(frame, text=title).grid(row=row, column=0, sticky="w", pady=6)
            variable = fields[key] = tk.StringVar(value=str(defaults[key]))
            ttk.Entry(frame, textvariable=variable, width=48).grid(row=row, column=1, sticky="ew", padx=10)
        auto = tk.BooleanVar(value=defaults["autostart"])
        ttk.Checkbutton(frame, text="已有可用 Profile / 密钥认证，自动开始抓包", variable=auto).grid(row=8, column=0, columnspan=2, sticky="w", pady=10)
        ttk.Label(frame, text="密码认证无需私钥。未勾选自动开始时：在 Wireshark 的 SSH remote capture\n齿轮配置中打开 Authentication，输入用户名/密码后点击 Start。", wraplength=560).grid(row=9, column=0, columnspan=2, sticky="w", pady=10)
        accepted = []
        def accept():
            defaults.update({key: var.get() for key, var in fields.items()}, autostart=auto.get())
            accepted.append(True); window.destroy()
        ttk.Button(frame, text="保存并继续", command=accept).grid(row=10, column=1, sticky="e")
        window.lift()
        window.focus_force()
        window.mainloop()
        if not accepted:
            raise ValueError("本地连接配置已取消")
    return validate_connection(defaults)


def discover(connection):
    executable = Path(connection["wireshark"])
    tshark = executable.with_name("tshark.exe" if os.name == "nt" else "tshark")
    if not tshark.is_file():
        found = shutil.which("tshark")
        if not found:
            raise ValueError("未找到 tshark，请安装完整 Wireshark（包括 SSH remote capture）")
        tshark = Path(found)
    def run(args):
        result = subprocess.run([str(tshark), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, creationflags=CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError("无法检查 Wireshark SSH 抓包组件：" + result.stderr.decode("utf-8", "replace")[-1000:])
        return result.stdout.decode("utf-8", "replace")
    names = re.findall(r"^\d+\. (\S+) .*", run(["-D"]), re.M)
    interface = next((name for name in names if name in ("sshdump", "sshdump.exe")), None)
    prefixes = re.findall(r"^#?extcap\.([\w]+)\.remotecapturecommand:", run(["-G", "defaultprefs"]), re.M)
    prefix = re.sub(r"[^\w]", "_", interface or "")
    if not interface or prefix not in prefixes:
        raise ValueError("未检测到支持自定义远端命令的 sshdump，请安装 Wireshark 的 SSH remote capture 组件")
    return interface, prefix


def preflight(connection):
    interface, prefix = discover(connection)
    # Wireshark otherwise exits immediately for a missing -C profile, while the
    # old windowless launcher discarded the error and left Web waiting for SSH.
    if connection["profile"]:
        executable = Path(connection["wireshark"])
        tshark = executable.with_name("tshark.exe" if os.name == "nt" else "tshark")
        result = subprocess.run([str(tshark), "-G", "folders", "-C", connection["profile"]],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, creationflags=CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError("Wireshark Profile 不存在或无法读取，请重新配置；不用 Profile 时留空")
    return interface, prefix


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("抓包后端发生重定向，请使用实际后端地址重新配置")


def claim(server, ticket):
    request = Request(server + "/api/capture/claim", data=json.dumps({"ticket": ticket}).encode(), headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
            data = response.read(32769)
            if len(data) > 32768:
                raise ValueError("抓包后端响应过大")
            value = json.loads(data)
    except Exception as exc:
        # Never include the ticket in diagnostics.
        raise ValueError("无法兑换抓包连接，请检查后端地址，或回到 Web 重新开始抓包") from exc
    if type(value.get("port")) is not int or not 1 <= value["port"] <= 65535 or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value.get("stream_ticket", "")):
        raise ValueError("抓包后端返回无效连接参数")
    return value


def remote_command(port, ticket):
    source = base64.b64encode((ROOT / "remote_relay.py").read_bytes()).decode("ascii")
    code = "import base64;exec(compile(base64.b64decode('" + source + "'),'<route-ovs-relay>','exec'))"
    return shlex.join(["python3", "-c", code, "--port", str(port), "--ticket", ticket])


def command(connection, interface, prefix, descriptor, output_file=None):
    result = [connection["wireshark"]]
    if connection["profile"]:
        result += ["-C", connection["profile"]]
    preferences = {"remotehost": connection["host"], "remoteport": str(connection["port"]), "remoteusername": connection["username"],
                   "remotecapturecommandselect": "other", "remotecapturecommand": remote_command(descriptor["port"], descriptor["stream_ticket"]),
                   "remotepriv": "none", "remoteinterface": "", "remotefilter": "", "remotecount": "0"}
    if connection["sshkey"]:
        preferences["sshkey"] = connection["sshkey"]
    for key, value in preferences.items():
        result += ["-o", f"extcap.{prefix}.{key}:{value}"]
    if output_file:
        # Wireshark 4.2 supports this preference but not the newer -F option.
        result += ["-w", str(output_file), "-o", "capture.pcap_ng:TRUE", "-S"]
    result += ["-i", interface]
    if connection["autostart"] and Path(connection["wireshark"]).stem.lower() != "tshark":
        result.append("-k")
    return result


def capture_file(connection, descriptor):
    directory = Path(connection.get("capture_dir") or default_capture_dir())
    directory.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^\w.-]+", "-", str(descriptor.get("session", {}).get("label", "capture")))[:60].strip("-.") or "capture"
    # A unique directory reserves the destination without overwriting any capture.
    folder = tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-") + label + "-", dir=directory)
    return Path(folder) / "capture.pcapng"


def report(server, descriptor, **payload):
    if not descriptor.get("client_ticket"):
        return  # Backwards compatible with an older server.
    request = Request(server + "/api/capture/client-report", data=json.dumps({"ticket": descriptor["client_ticket"], **payload}).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=8) as response:
            response.read(32768)
    except Exception:
        diagnostic("本地启动结果未能回传 Web；抓包连接仍可继续。")


def activate_window(pid):
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(visit, 0)
    for hwnd in found:
        user32.ShowWindow(hwnd, 9)  # Restore a minimized window.
        user32.SetForegroundWindow(hwnd)
    return bool(found)


def launch(connection, interface, prefix, descriptor, output_file):
    process = subprocess.Popen(command(connection, interface, prefix, descriptor, output_file), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, close_fds=True, start_new_session=os.name != "nt")
    errors = bytearray()
    def drain():
        try:
            while chunk := process.stderr.read1(4096):
                errors.extend(chunk)
                del errors[:-8192]
        finally:
            process.stderr.close()
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    started = time.monotonic()
    deadline = started + (15 if os.name == "nt" else 2)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            reader.join(timeout=1)
            detail = errors.decode("utf-8", "replace")
            for key in ("stream_ticket", "client_ticket"):
                if descriptor.get(key): detail = detail.replace(descriptor[key], "<凭证已隐藏>")
            diagnostic(f"Wireshark 提前退出，退出码 {process.returncode}。" + detail[-2000:])
            raise ValueError(f"Wireshark 提前退出（退出码 {process.returncode}），请检查程序路径和 Profile。诊断日志：{config_path().with_name('capture-launcher.log')}")
        # A splash screen can appear before command-line validation completes.
        if time.monotonic() - started >= 3 and activate_window(process.pid):
            break
        time.sleep(0.15)
    diagnostic("Wireshark 已启动；目标文件：" + str(output_file))
    # Keep draining stderr until Wireshark exits. Returning from the URL handler
    # immediately would close its pipe while the GUI is still using it.
    return process, reader


def notify_error(message):
    if sys.stderr:
        print(message, file=sys.stderr)
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "route-ovs 抓包", 0x10)
    elif os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("zenity"):
            subprocess.run(["zenity", "--error", "--title=route-ovs 抓包", "--text=" + message])


def main():
    # pythonw/PyInstaller windowed entry points have no console streams. Some
    # standard-library argparse paths still write to them (including --help).
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if os.name == "nt" and getattr(sys, "frozen", False):
        # External Wireshark/PowerShell must resolve their own DLLs, rather than
        # inheriting PyInstaller's extraction directory as a DLL search path.
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    if len(sys.argv) > 1 and sys.argv[1].startswith("route-ovs:") and len(sys.argv) != 2:
        raise ValueError("协议启动只接受一个完整抓包链接")
    parser = argparse.ArgumentParser(description="route-ovs 本地 Wireshark 启动器")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--configure", metavar="SERVER")
    parser.add_argument("--terminal", action="store_true", help="在终端配置，适用于无 Tk 的 Linux")
    parser.add_argument("--config", type=Path, default=config_path())
    args = parser.parse_args()
    config = load_config(args.config)
    server, ticket = (origin(args.configure), None) if args.configure else parse_uri(args.url) if args.url else (None, None)
    if server and ticket is None:
        config["connections"][server] = configure(server, config["connections"].get(server), args.terminal)
        save_config(args.config, config)
        return
    if not args.url:
        parser.error("需要抓包链接，或 --configure http://工作台地址:端口")
    if server not in config["connections"]:
        config["connections"][server] = configure(server, terminal=args.terminal)
        save_config(args.config, config)
    connection = validate_connection(config["connections"][server])
    interface, prefix = preflight(connection)
    descriptor = claim(server, ticket)
    try:
        output_file = capture_file(connection, descriptor)
        process, reader = launch(connection, interface, prefix, descriptor, output_file)
    except Exception as exc:
        report(server, descriptor, status="error", error=str(exc)[:1000].replace("\n", " ").replace("\r", " "))
        raise
    report(server, descriptor, status="launched", output_file=str(output_file), manual_auth=not connection["autostart"])
    process.wait()
    reader.join(timeout=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        notify_error(str(exc))
        sys.exit(1)
