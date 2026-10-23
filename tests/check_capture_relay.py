"""Verify an ordinary host user can relay fixture captures without sudo or PTY."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--metadata", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
fixture = json.loads(args.metadata.read_text())
lab = fixture["lab"]
assert lab.startswith("capture-test-")
args.output.mkdir(parents=True, exist_ok=True)
def api(path, method="GET", body=None):
    req = Request(f'http://127.0.0.1:{fixture["port"]}' + path, method=method,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={"Authorization": "Bearer capture-browser-check", "Content-Type": "application/json"})
    with urlopen(req, timeout=15) as response:
        return json.load(response)
issued = api(f"/api/labs/{lab}/captures", "POST", {"link": "wire1", "side": "b", "filter": "icmp"})
claim = api("/api/capture/claim", "POST", {"ticket": issued["ticket"]})
relay = Path(__file__).resolve().parents[1] / "clients" / "capture" / "remote_relay.py"
path = args.output / "relay-veth.pcap"
with path.open("wb") as output:
    proc = subprocess.Popen([sys.executable, str(relay), "--port", str(claim["port"]), "--ticket", claim["stream_ticket"]],
                            stdin=subprocess.PIPE, stdout=output, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            state = next(s for s in api(f"/api/labs/{lab}/captures") if s["id"] == issued["session"]["id"])
            if state["state"] == "running": break
            if proc.poll() is not None: raise AssertionError(proc.stderr.read().decode())
            time.sleep(0.1)
        assert state["state"] == "running", state
        cid = fixture["record"]["runtime"]["nodes"]["pc1"]["id"]
        subprocess.run(["docker", "exec", cid, "ping", "-c", "3", "-W", "1", "192.0.2.162"], check=True, stdout=subprocess.PIPE)
        time.sleep(0.3)
        proc.stdin.close()  # SSH channel EOF, including idle capture disconnection.
        proc.wait(timeout=5)
        assert proc.returncode == 0, proc.stderr.read().decode("utf-8", "replace")
        for _ in range(40):
            state = next(s for s in api(f"/api/labs/{lab}/captures") if s["id"] == issued["session"]["id"])
            if state["state"] == "stopped": break
            time.sleep(0.1)
        assert state["state"] == "stopped", state
    finally:
        api(f'/api/labs/{lab}/captures/{issued["session"]["id"]}', "DELETE")
        if proc.poll() is None: proc.kill(); proc.wait()
        if not proc.stdin.closed: proc.stdin.close()
        proc.stderr.close()
decoded = subprocess.run(["tcpdump", "-nn", "-r", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
assert "192.0.2.161 > 192.0.2.162: ICMP echo request" in decoded, decoded
assert "192.0.2.162 > 192.0.2.161: ICMP echo reply" in decoded, decoded
result = {"passed": True, "relay_uid": os.geteuid(), "bytes": path.stat().st_size, "state": state["state"], "icmp_packets": len(decoded.splitlines())}
(args.output / "relay-results.json").write_text(json.dumps(result))
print(json.dumps(result))
