#!/usr/bin/python3
"""Restage the already built Settings commit, retaining all daily deployments."""
from collections import Counter
import configparser
import hashlib
import json
import os
from pathlib import Path
import subprocess
from staged_state import read_staged

ROOT = Path('/var/tmp/sargo-fingerprint-mm-20260912/settings-fix-20260913')
BASE = 'd639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89'
TARGET = 'efa97ca47fa5962a46f9bfa5c8d50dada208cf299ef113c3e18b709f4a5bfe7a'
BOOT = '15c464d5-16f8-44fe-a3e0-96e6ee380310'
DEPLOYS = Path('/ostree/deploy/pocketfed/deploy')
NAMES = {'gnome-control-center', 'gnome-control-center-filesystem'}

def out(*args):
    return subprocess.check_output(args, text=True).strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, data):
    with (ROOT / name).open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())

def packages(root=None):
    args = ['rpm']
    if root:
        args += ['--dbpath', str(root / 'usr/share/rpm')]
    return out(*args, '-qa', '--qf', '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n').splitlines()

assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
assert 'androidboot.serialno=994AY18RSD' in Path('/proc/cmdline').read_text().split()
assert out('getenforce') == 'Enforcing'
state = json.loads(out('rpm-ostree', 'status', '--json'))
assert state['transaction'] is None and not any(d.get('staged') for d in state['deployments'])
booted = next(d for d in state['deployments'] if d['booted'])
assert booted['checksum'] == BASE and booted['pinned']
before = json.loads((ROOT / 'stage-attempt.json').read_text())
assert before['boot_id'] == BOOT
assert Counter(packages()) == Counter(before['before_packages'])
cached = DEPLOYS / (TARGET + '.0')
origin = DEPLOYS / (TARGET + '.0.origin')
assert sha(origin) == 'c5dbeeba131f0e87f37cb4bf1acc6d8ecc8769939b4cefa28950552b44d20eae'
assert Counter(packages(cached)) == Counter(before['expected_packages'])
for name, digest in before['protected_files'].items():
    assert sha(Path(name)) == digest
    assert sha(cached / name.lstrip('/')) == digest
assert sha(cached / 'usr/bin/gnome-control-center') == 'bdd71e22962d8bb08b2ba7ac762a54d92a7dba439aa2c95ac048fc8c641cea31'

# Reuse the exact original package transaction's origin, with its two added
# replacements. All remaining persistent configuration must match this boot.
current_origin = DEPLOYS / (BASE + '.' + str(booted['serial']) + '.origin')
configs = []
for path in (current_origin, origin):
    c = configparser.ConfigParser(interpolation=None)
    c.read(path)
    configs.append({s: dict(c[s]) for s in c.sections() if s != 'libostree-transient'})
old, new = configs
old_replacements = set(old['overrides'].pop('replace-local').strip(';').split(';'))
new_replacements = set(new['overrides'].pop('replace-local').strip(';').split(';'))
assert old == new and old_replacements <= new_replacements
assert new_replacements - old_replacements == {
    'c7192619268214631c2155e10e95a10354fb18a568279684319e519e31e837d5:gnome-control-center-51~rc.1-1.2.fingerprint.fc46.aarch64',
    '255a7e571fe525873605e0bfcadc60760d107f35f85b1027511f95b76e398903:gnome-control-center-filesystem-51~rc.1-1.2.fingerprint.fc46.noarch',
}
save('cached-stage-attempt.json', {'boot_id': BOOT, 'base': BASE, 'target': TARGET,
                                 'origin_sha256': sha(origin), 'reboot': False,
                                 'finalization_locked': True, 'retain_all': True})
subprocess.run(['ostree', 'admin', 'deploy', '--os=pocketfed', '--stage',
                '--lock-finalization', '--retain', '--no-prune',
                '--origin-file=' + str(origin), TARGET], check=True)
after = json.loads(out('rpm-ostree', 'status', '--json'))
staged = [d for d in after['deployments'] if d.get('staged')]
assert len(staged) == 1 and staged[0]['checksum'] == TARGET
staged = staged[0]
checkout = DEPLOYS / (TARGET + '.' + str(staged['serial']))
assert Counter(packages(checkout)) == Counter(before['expected_packages'])
assert {d['id'] for d in state['deployments']} <= {d['id'] for d in after['deployments']}
assert {d['checksum'] for d in state['deployments'] if d.get('pinned')} <= {
    d['checksum'] for d in after['deployments'] if d.get('pinned')}
for name, digest in before['protected_files'].items():
    assert sha(Path(name)) == digest
    assert sha(checkout / name.lstrip('/')) == digest
# Staging defers the /etc merge until finalization. Verify the recorded merge
# source and boot payload instead of expecting current masks in the cached tree.
pending = read_staged()
assert pending['locked']
assert pending['target']['name'] == checkout.name
assert pending['merge_deployment']['name'] == BASE + '.' + str(booted['serial'])
assert pending['target']['bootcsum'] == pending['merge_deployment']['bootcsum']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
save('cached-stage-result.json', {'status': 'cached Settings deployment staged',
                                'target': TARGET, 'serial': staged['serial'],
                                'package_delta': sorted(NAMES), 'protected_files_unchanged': True,
                                'reboot': False, 'applied_live': False,
                                'finalization_locked': True, 'pins_retained': True,
                                'configuration_merge_deferred': True,
                                'staged_state': pending})
print('Verified cached Settings update staged with finalization locked; live desktop unchanged.')
