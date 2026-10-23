"""Root-only disposable backend for real local sshdump and browser checks."""
import argparse
import json
import os
import threading
from pathlib import Path
import uvicorn
from test_capture_docker import CaptureDockerFixture
from lab_server import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8106)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--lifetime", type=int, default=600, help="Automatically stop and clean the disposable lab")
    args = parser.parse_args()
    fixture = CaptureDockerFixture()
    try:
        fixture.start()
        metadata = {"lab": fixture.lab_id, "port": args.port, "pid": os.getpid(), "record": fixture.manager.read(fixture.lab_id)}
        args.metadata.write_text(json.dumps(metadata), encoding="utf-8")
        print(json.dumps({"lab": fixture.lab_id, "port": args.port, "pid": os.getpid()}), flush=True)
        server = uvicorn.Server(uvicorn.Config(create_app(fixture.manager, "capture-browser-check", capture_port=args.port), host="127.0.0.1", port=args.port, log_level="warning"))
        timer = threading.Timer(args.lifetime, lambda: setattr(server, "should_exit", True))
        timer.daemon = True
        timer.start()
        try:
            server.run()
        finally:
            timer.cancel()
    finally:
        fixture.cleanup()
