"""Resource locations and host-command environment for source and Linux bundles."""
import os
from pathlib import Path
import sys


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def default_data_dir():
    # Writable state must never live inside a versioned installation or _internal.
    return Path("/var/lib/route-ovs") if getattr(sys, "frozen", False) else resource_root() / ".route-ovs-labs"


def host_environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False) and sys.platform == "linux":
        # Docker, nsenter and tcpdump need the host's libraries, not PyInstaller's.
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    return env
