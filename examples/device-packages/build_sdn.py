#!/usr/bin/env python3
"""Build three device wrappers and pack clean, offline .lwns archives."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'script/python'))
from lab_device_packages import inspect_package, pack_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--force', action='store_true', help='replace output archives; does not update installed device versions')
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    roles = ('sdn-agent', 'sdn-controller', 'sdn-web')
    for role in roles:
        definition = json.loads((ROOT / 'examples/device-packages' / role / 'device.json').read_text())
        if (output / (role + '-' + definition['version'] + '.lwns')).exists() and not args.force:
            parser.error('output exists; choose another directory or explicitly use --force')
    evidence = {}
    for role in roles:
        folder = ROOT / 'examples/device-packages' / role
        definition = json.loads((folder / 'device.json').read_text())
        base = json.loads(subprocess.check_output(['docker', 'image', 'inspect', role + ':alpine']))[0]
        if base['Os'] != 'linux' or base['Architecture'] != 'amd64':
            raise SystemExit('This definition requires a Linux amd64 base: ' + role)
        log = output / (role + '-build.log')
        # BuildKit cannot use a bare local sha256 ID as FROM. Pin that ID to a
        # unique temporary tag so changes to :alpine do not affect this build.
        base_tag = 'lwns/build-base-' + role + ':' + uuid.uuid4().hex
        subprocess.run(['docker', 'tag', base['Id'], base_tag], check=True)
        try:
            with log.open('w') as stream:
                subprocess.run(['docker', 'build', '--pull=false', '--build-arg', 'BASE_IMAGE=' + base_tag,
                                '-t', definition['image'], str(folder)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        finally:
            subprocess.run(['docker', 'image', 'rm', '--no-prune', base_tag], stdout=subprocess.DEVNULL, check=True)
        print('Built ' + role, flush=True)
        with tempfile.TemporaryDirectory(prefix='.image-', dir=output) as temporary:
            image_tar = Path(temporary) / 'image.tar'
            subprocess.run(['docker', 'save', '-o', str(image_tar), definition['image']], check=True)
            package = output / (role + '-' + definition['version'] + '.lwns')
            report = pack_device(definition, package, image_tar=image_tar, overwrite=args.force)
            inspected = inspect_package(package)
        image_id = json.loads(subprocess.check_output(['docker', 'image', 'inspect', definition['image']]))[0]['Id']
        evidence[role] = dict(base_image_id=base['Id'], image_id=image_id, package=package.name,
                              sha256=inspected['package_sha256'], bytes=package.stat().st_size)
        print('Packed and verified ' + str(package), flush=True)
    (output / 'build-manifest.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(row['sha256'] + '  ' + row['package'] + '\n' for row in evidence.values()))


if __name__ == '__main__':
    main()
