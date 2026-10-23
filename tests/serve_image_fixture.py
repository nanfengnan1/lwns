"""Disposable image manager backend for check_images.cjs (Docker group is enough)."""
import argparse
import json
import os
from pathlib import Path
import uvicorn
from test_images_docker import ImageDockerFixture

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8104)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--large-library", action="store_true")
    args = parser.parse_args()
    fixture = ImageDockerFixture()
    try:
        metadata = fixture.prepare_archive()
        metadata["pid"] = os.getpid()
        if args.large_library:
            catalog = fixture.images.catalog
            def large_catalog():
                items = catalog()
                return items + [{**items[0], "id": f"fixture-{i}", "template_id": "frr", "title": f"测试路由器 {i:03}", "image": f"fixture/router-{i}:latest"} for i in range(200)]
            fixture.images.catalog = large_catalog
        args.metadata.write_text(json.dumps(metadata), encoding="utf-8")
        print(json.dumps(metadata), flush=True)
        uvicorn.run(fixture.app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        fixture.cleanup()
