#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 - "$source_dir" <<'PY'
import os
from pathlib import Path
import shutil
import subprocess
import sys
source = Path(sys.argv[1])
data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
destination = data / 'lwns-capture'
destination.mkdir(parents=True, exist_ok=True)
for name in ('launcher.py', 'remote_relay.py', 'README.md'):
    target = destination / name
    if (source / name).resolve() != target.resolve():
        shutil.copyfile(source / name, target)
def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
entry = data / 'applications' / 'lwns-capture.desktop'
entry.parent.mkdir(parents=True, exist_ok=True)
entry.write_text('[Desktop Entry]\nType=Application\nName=lwns Capture\nNoDisplay=true\nTerminal=false\n'
                 'Exec=' + quoted(sys.executable) + ' ' + quoted(destination / 'launcher.py') + ' %u\n'
                 'MimeType=x-scheme-handler/lwns;\n', encoding='utf-8')
if shutil.which('update-desktop-database'):
    subprocess.run(['update-desktop-database', str(entry.parent)], check=True)
if not shutil.which('xdg-mime'):
    sys.exit('Install xdg-utils, then run: xdg-mime default lwns-capture.desktop x-scheme-handler/lwns')
subprocess.run(['xdg-mime', 'default', entry.name, 'x-scheme-handler/lwns'], check=True)
print('Installed lwns URL handler. Python 3.10+ and python3-tk are needed for the setup dialog.')
print('Headless setup: python3 ' + str(destination / 'launcher.py') + ' --configure http://HOST:8090 --terminal')
PY
