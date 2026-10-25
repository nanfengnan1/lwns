"""Disposable .rov browser fixture. All Docker calls use PackageHost fakes."""
import argparse
import os
import tempfile

import uvicorn
from test_device_package_api import PackageHost
from test_lab import LabManager
from lab_device_service import DevicePackageService
from lab_images import ImageService
from lab_server import create_app


class PackageManager(LabManager):
    def environment(self):
        return {"ready": True, "preview": False, "errors": [],
                "images": ["alpine/frr:latest", "alpine/vpcs:latest"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8110)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lwns-packages-browser-") as directory:
        host = PackageHost()
        manager = PackageManager(directory, runner=host)
        manager.authorize = lambda: None
        images = ImageService(manager, command=host.command)
        packages = DevicePackageService(manager, images, command=host.command)
        print(f"Package fixture PID {os.getpid()}: http://127.0.0.1:{args.port}/#token=package-browser-check", flush=True)
        try:
            uvicorn.run(create_app(manager, "package-browser-check", images=images, device_packages=packages),
                        host="127.0.0.1", port=args.port, ws="websockets-sansio", log_level="warning",
                        timeout_graceful_shutdown=5)
        finally:
            packages.wait()
            images.wait()
