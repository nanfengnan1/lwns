"""Real local sshdump -> SSH -> isolated fixture -> veth capture; no SSH password arguments.

python check_capture_ssh.py --metadata fixture.json --server http://127.0.0.1:18106
  --wireshark /path/to/Wireshark.exe --profile EXISTING_PROFILE --host HOST --username USER --output DIR
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients" / "capture"))
import launcher


def main():
    parser = argparse.ArgumentParser()
    for name in ("metadata", "server", "wireshark", "profile", "host", "username", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    fixture = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
    lab = fixture["lab"]
    assert lab.startswith("capture-test-"), "Use the isolated capture fixture only"
    folder = Path(args.output); folder.mkdir(parents=True, exist_ok=True)
    def api(path, method="GET", body=None):
        request = Request(args.server + path, method=method, headers={"Authorization": "Bearer capture-browser-check", "Content-Type": "application/json"},
                          data=None if body is None else json.dumps(body).encode())
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    connection = launcher.validate_connection({"wireshark": args.wireshark, "host": args.host, "port": 22, "username": args.username,
                                               "profile": args.profile, "sshkey": "", "autostart": True})
    interface, prefix = launcher.discover(connection)
    tshark = Path(args.wireshark).with_name("tshark.exe" if os.name == "nt" else "tshark")
    connection["wireshark"] = str(tshark)
    issued = api(f"/api/labs/{lab}/captures", "POST", {"link": "wire1", "side": "a", "filter": "icmp", "snaplen": 128})
    descriptor = launcher.claim(args.server, issued["ticket"])
    output = folder / "ssh-veth.pcapng"
    command = launcher.command(connection, interface, prefix, descriptor) + ["-a", "duration:8", "-w", str(output)]
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(150):
            state = next(s for s in api(f"/api/labs/{lab}/captures") if s["id"] == issued["session"]["id"])
            if state["state"] == "running":
                break
            if proc.poll() is not None:
                raise AssertionError(proc.stderr.read().decode("utf-8", "replace").replace(descriptor["stream_ticket"], "<ticket>"))
            time.sleep(0.2)
        else:
            raise AssertionError("sshdump did not connect: " + state["state"])
        cid = fixture["record"]["runtime"]["nodes"]["pc1"]["id"]
        subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", args.username + "@" + args.host, "docker", "exec", cid, "ping", "-c", "3", "-W", "1", "192.0.2.162"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        _, stderr = proc.communicate(timeout=15)
        assert proc.returncode == 0, stderr.decode("utf-8", "replace").replace(descriptor["stream_ticket"], "<ticket>")
        decoded = subprocess.run([str(tshark), "-r", str(output), "-Y", "icmp", "-T", "fields", "-e", "ip.src", "-e", "ip.dst"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
        assert "192.0.2.161\t192.0.2.162" in decoded, decoded
        assert "192.0.2.162\t192.0.2.161" in decoded, decoded
        for _ in range(40):
            state = next(s for s in api(f"/api/labs/{lab}/captures") if s["id"] == issued["session"]["id"])
            if state["state"] == "stopped": break
            time.sleep(0.2)
        assert state["state"] == "stopped", state
        result = {"passed": True, "interface": interface, "preference_prefix": prefix, "icmp_packets": len(decoded.splitlines()), "bytes": state["bytes"], "state": state["state"]}
        (folder / "ssh-results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    finally:
        api(f'/api/labs/{lab}/captures/{issued["session"]["id"]}', "DELETE")
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        proc.stderr.close()


if __name__ == "__main__":
    main()
