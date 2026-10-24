"""Device-library UI fixture. Every Docker/image command uses ImageHost, never the host."""
import argparse
import os
import tempfile
import uvicorn
from test_images import ImageHost, ImageService, LabManager, create_app

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8107)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="route-ovs-library-") as directory:
    host = ImageHost()
    manager = LabManager(directory, runner=host)
    images = ImageService(manager, command=host.command)
    for index in range(200):
        ref = f"fixture/router-{index:03}:latest"
        host.images[ref] = "sha256:" + f"{index+100:064x}"
        images.registry["images"].append(images.new_entry(ref, {"template": "frr", "title": f"测试路由器 {index:03}"}))
    ref = "fixture/switch:latest"
    host.images[ref] = "sha256:" + "f" * 64
    images.registry["images"].append(images.new_entry(ref, {"template": "linux-bridge", "title": "测试交换机"}))
    images.sync()
    print(f"Library fixture PID {os.getpid()}: http://127.0.0.1:{args.port}/#token=library-check", flush=True)
    try:
        uvicorn.run(create_app(manager, "library-check", images=images), host="127.0.0.1", port=args.port,
                    ws="websockets-sansio", log_level="warning", timeout_graceful_shutdown=5)
    finally:
        images.wait()
