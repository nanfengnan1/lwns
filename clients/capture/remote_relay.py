"""Run as the ordinary SSH user; relay a ticketed loopback PCAP stream to stdout."""
import argparse
import http.client
import json
import os
import re
import signal
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", args.ticket):
        parser.error("Invalid capture connection")
    connection = http.client.HTTPConnection("127.0.0.1", args.port, timeout=15)
    def interrupted(*_):
        # Process exit closes the socket atomically; closing it from this watcher
        # would race the main thread's read and report a normal EOF as an error.
        os._exit(0)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    # SSH exec channels close stdin on disconnect, even when no packets arrive.
    def disconnected():
        try:
            while sys.stdin.buffer.read(1):
                pass
        except OSError:
            pass
        interrupted()
    threading.Thread(target=disconnected, daemon=True).start()
    try:
        connection.request("POST", "/api/capture/stream", json.dumps({"ticket": args.ticket}), {"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            detail = response.read(8192).decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            raise RuntimeError(detail)
        if connection.sock:
            connection.sock.settimeout(None)
        while data := response.read1(65536):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except BrokenPipeError:
        return
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("lwns capture: " + str(error), file=sys.stderr)
        sys.exit(1)
