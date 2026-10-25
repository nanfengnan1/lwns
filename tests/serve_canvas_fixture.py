"""Isolated running-edit UI fixture; all Docker/image calls use ImageHost fakes."""
import argparse
import os
import tempfile
import time
import uvicorn
from test_lab import LabManager, create_app, example
from test_images import ImageHost, ImageService


class CanvasHost(ImageHost):
    delay_links = False

    def __call__(self, argv, **kwargs):
        if self.delay_links and argv[:3] == ["ip", "link", "add"]:
            time.sleep(1)  # Keep the updating state observable to the UI check.
        return super().__call__(argv, **kwargs)


class CanvasManager(LabManager):
    def environment(self):
        return {"ready": True, "preview": False, "errors": [],
                "images": ["alpine/frr:latest", "alpine/vpcs:latest"]}


parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8106)
parser.add_argument("--host", default="127.0.0.1", help="Bind address for this isolated FakeHost fixture")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="lwns-canvas-") as directory:
    host = CanvasHost()
    manager = CanvasManager(directory, runner=host)
    images = ImageService(manager, command=host.command)
    topology = example()
    topology["annotations"] = [{"id": "note-subnet", "text": "10.10.1.0/24", "x": -180, "y": 120}]
    record = manager.save(topology)
    manager.deploy(record)
    host.delay_links = True
    print(f"Canvas fixture PID {os.getpid()}: http://{args.host}:{args.port}/#token=canvas-scroll-check", flush=True)
    uvicorn.run(create_app(manager, "canvas-scroll-check", images=images), host=args.host, port=args.port,
                ws="websockets-sansio", log_level="warning", timeout_graceful_shutdown=5)
