"""Isolated running-layout UI fixture; FakeHost never executes Docker or host commands."""
import argparse
import os
import tempfile
import uvicorn
from test_lab import FakeHost, LabManager, create_app, example

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8106)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="route-ovs-canvas-") as directory:
    manager = LabManager(directory, runner=FakeHost(), preview=True)
    topology = example()
    topology["annotations"] = [{"id": "note-subnet", "text": "10.10.1.0/24", "x": -180, "y": 120}]
    record = manager.save(topology)
    manager.deploy(record)
    print(f"Canvas fixture PID {os.getpid()}: http://127.0.0.1:{args.port}/#token=canvas-scroll-check", flush=True)
    uvicorn.run(create_app(manager, "canvas-scroll-check"), host="127.0.0.1", port=args.port,
                ws="websockets-sansio", log_level="warning", timeout_graceful_shutdown=5)
