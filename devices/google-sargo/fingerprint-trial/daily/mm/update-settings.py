#!/usr/bin/python3
"""Stage or apply the two verified Settings RPMs on daily sam-sargo, without reboot."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
assert ROOT.parent == Path('/var/tmp/sargo-fingerprint-mm-20260912')
assert ROOT.name in {'settings-fix', 'settings-fix-after-usb-reboot', 'settings-fix-20260913'}
BASE = 'd639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89'
PIN = '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
NAMES = {'gnome-control-center', 'gnome-control-center-filesystem'}
FORMAT = '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'

def out(*args):
    return subprocess.check_output(args, text=True).strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save_new(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())

def packages(root=None):
    args = ['rpm']
    if root:
        args += ['--dbpath', str(root / 'usr/share/rpm')]
    return sorted(out(*args, '-qa', '--qf', FORMAT).splitlines())

assert os.getuid() == os.geteuid() == 0
assert sys.argv[1:] in (['stage'], ['apply-live'])
assert [x for x in Path('/proc/cmdline').read_text().split()
        if x.startswith('androidboot.serialno=')] == ['androidboot.serialno=994AY18RSD']
assert out('getenforce') == 'Enforcing'
assert sha(Path('/etc/pam.d/phosh')) == PIN
state = json.loads(out('rpm-ostree', 'status', '--json'))
assert state['transaction'] is None
booted = next(d for d in state['deployments'] if d['booted'])
assert booted['checksum'] == BASE
manifest = json.loads((ROOT / 'manifest.json').read_text())
assert set(manifest['packages']) == NAMES
assert len(manifest['files']) == 2
rpms = []
for name, digest in manifest['files'].items():
    assert Path(name).name == name and name.endswith('.rpm')
    path = ROOT / name
    assert path.is_file() and not path.is_symlink() and sha(path) == digest
    record = out('rpm', '-qp', '--qf', FORMAT, str(path))
    assert record == manifest['packages'][record.split('\t')[0]]
    rpms.append(str(path))

if sys.argv[1] == 'stage':
    assert not any(d.get('staged') for d in state['deployments'])
    before = packages()
    desired = sorted([p for p in before if p.split('\t')[0] not in NAMES]
                     + list(manifest['packages'].values()))
    protected = ['/etc/pam.d/phosh', '/etc/selinux/targeted/policy/policy.35',
                 '/usr/libexec/phosh', '/usr/bin/pocketfed-fpc-auth', '/usr/bin/qsee-sargo-rpmb']
    evidence = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'before_packages': before, 'expected_packages': desired,
                'protected_files': {p: sha(Path(p)) for p in protected},
                'pins': [d['checksum'] for d in state['deployments'] if d.get('pinned')],
                'requests': {k: v for k, v in booted.items() if k.startswith('requested-')},
                'manifest_sha256': sha(ROOT / 'manifest.json'), 'reboot': False}
    save_new('stage-attempt.json', evidence)
    index = next(i for i, d in enumerate(state['deployments']) if d['booted'])
    subprocess.run(['ostree', 'admin', 'pin', str(index)], check=True)
    subprocess.run(['rpm-ostree', 'override', 'replace', '--cache-only', '--lock-finalization', *rpms], check=True)
else:
    before = json.loads((ROOT / 'stage-attempt.json').read_text())
    assert before['manifest_sha256'] == sha(ROOT / 'manifest.json')
    staged = [d for d in state['deployments'] if d.get('staged')]
    assert len(staged) == 1
    staged = staged[0]
    checkout = Path('/ostree/deploy') / staged['osname'] / 'deploy' / (staged['checksum'] + '.' + str(staged['serial']))
    assert Counter(packages(checkout)) == Counter(before['expected_packages'])
    assert set(before['pins']) | {BASE} <= {d['checksum'] for d in state['deployments'] if d.get('pinned')}
    for name, digest in before['protected_files'].items():
        assert sha(Path(name)) == digest
        assert sha(checkout / name.lstrip('/')) == digest
    for key, value in before['requests'].items():
        if key == 'requested-base-local-replacements':
            assert set(value) <= set(staged[key])
            assert len(staged[key]) == len(value) + 2
        else:
            assert staged[key] == value, key
    save_new('live-apply-attempt.json', {'target': staged['checksum'], 'verified_package_delta': sorted(NAMES), 'reboot': False})
    subprocess.run(['rpm-ostree', 'apply-live', '--target', staged['checksum'], '--allow-replacement'], check=True)
    assert Counter(packages()) == Counter(before['expected_packages'])
    for name, digest in before['protected_files'].items():
        assert sha(Path(name)) == digest
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == before['boot_id']
    # The verified update becomes the normal next boot; this does not reboot.
    subprocess.run(['ostree', 'admin', 'lock-finalization', '--unlock'], check=True)
    save_new('live-apply-result.json', {'status': 'Settings-only update applied live', 'target': staged['checksum'],
                                      'package_delta': sorted(NAMES), 'protected_files_unchanged': True,
                                      'boot_id_unchanged': True, 'reboot': False, 'next_boot_finalization_unlocked': True})
    print('Settings-only update applied live; protected files and boot ID unchanged.')
