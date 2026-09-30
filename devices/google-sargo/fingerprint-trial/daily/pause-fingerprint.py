#!/usr/bin/python3
"""Persist the narrow fingerprint pause after the masked daily recovery boot."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

assert os.geteuid() == 0
DEPLOYMENT = 'd639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89'
RELEASE = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
PIN_SHA = '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
UNITS = ['fprintd.service', 'phosh-fingerprint-auth.socket',
         'phosh-fingerprint-auth@.service']
run = lambda argv: subprocess.check_output(argv, text=True).strip()
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
cmdline = Path('/proc/cmdline').read_text().split()
assert 'androidboot.serialno=994AY18RSD' in cmdline
assert os.uname().release == RELEASE
assert all('systemd.mask=' + unit in cmdline for unit in UNITS)
assert run(['getenforce']) == 'Enforcing'
assert sha('/etc/pam.d/phosh') == PIN_SHA
deployments = json.loads(run(['rpm-ostree', 'status', '--json']))['deployments']
booted = [deployment for deployment in deployments if deployment.get('booted')]
assert len(booted) == 1 and booted[0]['checksum'] == DEPLOYMENT
for unit in UNITS[:2]:
    assert run(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive'
instances = json.loads(run(['systemctl', 'list-units', '--all', '--output=json',
                            'phosh-fingerprint-auth@*.service']))
assert all(unit['active'] in ('inactive', 'failed') for unit in instances)
unit_dir = Path('/etc/systemd/system')
before = {}
for unit in UNITS:
    path = unit_dir / unit
    assert not os.path.lexists(path) or (path.is_symlink() and os.readlink(path) == '/dev/null'), unit
    before[unit] = os.readlink(path) if path.is_symlink() else None
receipt_dir = Path('/var/tmp/sargo-fingerprint-mm-20260912/paused-recovery')
receipt_dir.mkdir(mode=0o700)
receipt = {'serial': '994AY18RSD', 'deployment': DEPLOYMENT,
           'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
           'started_at': time.time(), 'before': before, 'units': UNITS,
           'pin_pam_sha256': PIN_SHA,
           'purpose': 'Prevent automatic sensor initialization across ordinary reboots while kernel freeze is investigated'}
(receipt_dir / 'attempt.json').write_text(json.dumps(receipt, indent=2) + '\n')
subprocess.run(['systemctl', 'mask', *UNITS], check=True)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
for unit in UNITS:
    assert os.readlink(unit_dir / unit) == '/dev/null'
    # `show` accepts an instantiated unit, not a bare template name.
    check_unit = unit.replace('@.', '@pause-check.')
    assert run(['systemctl', 'show', check_unit, '-p', 'LoadState', '--value']) == 'masked'
assert sha('/etc/pam.d/phosh') == PIN_SHA
receipt['status'] = 'persistent fingerprint pause verified'
receipt['completed_at'] = time.time()
(receipt_dir / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
