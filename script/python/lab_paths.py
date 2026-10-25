"""Resource locations and host-command environment for source and Linux bundles."""
import os
from pathlib import Path
import sys


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def environment_setting(name, default=None):
    """Prefer LWNS settings while allowing existing launch scripts to keep working."""
    return os.environ.get("LWNS_" + name) or os.environ.get("ROUTE_OVS_" + name) or default


def default_data_dir():
    # Keep active bind mounts at their original paths; never migrate on startup.
    configured = environment_setting("DATA_DIR")
    if configured:
        return Path(configured)
    if getattr(sys, "frozen", False):
        current, legacy = Path("/var/lib/lwns"), Path("/var/lib/route-ovs")
    else:
        current, legacy = resource_root() / ".lwns-labs", resource_root() / ".route-ovs-labs"
    return legacy if not current.exists() and legacy.is_dir() else current


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
