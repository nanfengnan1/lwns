"""Manual browser fixture: creates two disposable Docker devices, cleans up on exit."""
import argparse
import os
import uvicorn
from test_terminal import DockerFixture
from lab_server import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8098)
args = parser.parse_args()
fixture = DockerFixture()
try:
    fixture.start()
    # The fixture has no veth links; real namespace checks require root.
    fixture.manager.status = lambda lab_id: fixture.manager.read(lab_id)
    print("Fixture PID {}: http://127.0.0.1:{}/#token=terminal-browser-check".format(os.getpid(), args.port), flush=True)
    uvicorn.run(create_app(fixture.manager, "terminal-browser-check"), host="127.0.0.1", port=args.port,
                ws="websockets-sansio", log_level="warning", timeout_graceful_shutdown=8)
finally:
    fixture.close()
