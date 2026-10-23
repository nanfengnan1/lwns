"""Disposable real deployment for check_configs.cjs; run as root on Linux."""
import argparse
import uvicorn
from test_config_docker import ConfigDockerFixture
from lab_server import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8102)
    args = parser.parse_args()
    fixture = ConfigDockerFixture()
    try:
        fixture.start()
        print("Config test lab: " + fixture.lab_id, flush=True)
        uvicorn.run(create_app(fixture.manager, "config-browser-check"), host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        fixture.cleanup()
