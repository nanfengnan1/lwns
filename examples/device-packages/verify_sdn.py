#!/usr/bin/env python3
"""Opt-in real Docker test; uses a unique lab and never opens the user's lab data.

sudo python3 examples/device-packages/verify_sdn.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'script/python'))
from lab_core import LabManager
from lab_device_packages import pack_device


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run on the Docker host as root for isolated veth tests.')
    test_root = Path(tempfile.mkdtemp(prefix='lwns-sdn-verify-'))
    manager = LabManager(test_root / 'data')
    manager.authorize()
    lab = 'sdn-rov-' + uuid.uuid4().hex[:10]
    nodes = []
    for role in ('sdn-controller', 'sdn-agent', 'sdn-web'):
        definition = json.loads((ROOT / 'examples/device-packages' / role / 'device.json').read_text())
        definition['source'] = {'type': 'repository'}
        image = json.loads(manager.dock('image', 'inspect', definition['image']))[0]['Id']
        package = test_root / (role + '.lwns')
        pack_device(definition, package)
        entry = manager.device_library.register(package, image_id=image)
        node_id = role.removeprefix('sdn-')
        addresses = {'controller': ['198.18.240.1/30', '198.18.241.1/30'],
                     'agent': ['198.18.240.2/30'], 'web': ['198.18.241.2/30']}[node_id]
        nodes.append(dict(id=node_id, name=node_id, kind=definition['category'], template=entry['id'],
                          image=image, ports=[dict(name='eth' + str(i), address=address) for i, address in enumerate(addresses)],
                          command=[], config='', gateway='', x=100, y=100))
    links = [dict(id='agent-mgmt', a=dict(node='controller', port='eth0'), b=dict(node='agent', port='eth0')),
             dict(id='web-mgmt', a=dict(node='controller', port='eth1'), b=dict(node='web', port='eth0'))]
    record = manager.save(dict(version=1, id=lab, name='Isolated SDN device validation', nodes=nodes, links=links))

    def execute(node, *args, **kwargs):
        cid = manager.read(lab)['runtime']['nodes'][node]['id']
        return manager.dock('exec', '-i', '-u', '0', cid, *args, **kwargs)

    def config_path(node):
        return test_root / 'data/devices' / lab / node / 'config' / (node + '.conf')

    def agent_cli(*args):
        code = "import json,os,subprocess,sys; c=json.load(open('/etc/sdn-agent/agent.conf')); os.environ['SDN_TOKEN']=c['agent']['token']; subprocess.run(['sdnctl','-insecure',*sys.argv[1:]],check=True)"
        return execute('agent', 'python3', '-c', code, *args, timeout=90)

    def web_nodes():
        code = "import json,urllib.request; c=json.load(open('/etc/sdn-web/web.conf')); r=urllib.request.Request('http://127.0.0.1:8080/api/v1/nodes',headers={'Authorization':'Bearer '+c['adminToken']}); print(urllib.request.urlopen(r,timeout=10).read().decode())"
        return json.loads(execute('web', 'python3', '-c', code))

    try:
        manager.deploy(record)
        print('PASS: all three descriptors deploy with native service readiness', flush=True)
        controller = json.loads(config_path('controller').read_text())['controller']
        agent = json.loads(config_path('agent').read_text())
        agent['agent'].update(controller='198.18.240.1:19090', endpoint='198.18.240.2:9090', token=controller['agentToken'])
        config_path('agent').write_text(json.dumps(agent))
        web = json.loads(config_path('web').read_text())
        web.update(controller='198.18.241.1:19090', adminToken=controller['adminToken'], viewerToken=controller['viewerToken'])
        config_path('web').write_text(json.dumps(web))
        for node in ('agent', 'web'):
            execute(node, 'sdn-device', 'restart', timeout=260)
        for _ in range(20):
            listing = web_nodes()
            if listing.get('items'):
                break
            time.sleep(1)
        assert listing.get('items'), 'Agent not registered through real Web -> Controller path'
        print('PASS: Agent registration and authenticated Web -> Controller API', flush=True)
        operations = {'operations': [{'id': 'bridge', 'code': 'BD', 'action': 'CREATE',
                                     'bridge': {'name': 'rovtest', 'stp': False, 'mtu': 1500}}]}
        execute('agent', 'python3', '-c', "import sys;open('/tmp/rov-ops.json','w').write(sys.stdin.read())", input_text=json.dumps(operations))
        agent_cli('-file', '/tmp/rov-ops.json', 'submit')
        before = json.loads(agent_cli('state'))
        assert int(before['revision']) == 1
        execute('agent', 'ip', 'link', 'show', 'rovtest')
        saved = manager.save_project(manager.read(lab)['topology'])
        assert all(row['ok'] for row in saved['results']), saved['results']
        print('PASS: Agent commit, Redis SAVE, FRR save, etcd snapshot, Web config save', flush=True)
        old = manager.read(lab)
        manager.destroy(old)
        # A new manager and new containers must recover from per-device persistence.
        manager = LabManager(test_root / 'data')
        manager.deploy(manager.read(lab))
        after = json.loads(agent_cli('state'))
        assert after['node_id'] == before['node_id']
        assert after['instance_id'] != before['instance_id']
        assert int(after['revision']) == 1
        assert web_nodes().get('items')
        code = "import subprocess; assert subprocess.run(['ip','link','show','rovtest'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0"
        execute('agent', 'python3', '-c', code)
        print('PASS: identity/revision/controller inventory survive recreation; REL-004 confirmed (bridge is not rebuilt)', flush=True)
        print('Evidence directory: ' + str(test_root), flush=True)
    finally:
        current = manager.read(lab)
        for node, runtime in current['runtime'].get('nodes', {}).items():
            # Keep failure logs inside the private evidence directory, not stdout.
            try:
                output = manager.dock('logs', '--tail', '100', runtime['id'], check=False)
                (test_root / (node + '.log')).write_text(output)
            except Exception:
                pass
        manager.destroy(current)
        os.chmod(test_root, 0o700)


if __name__ == '__main__':
    main()
