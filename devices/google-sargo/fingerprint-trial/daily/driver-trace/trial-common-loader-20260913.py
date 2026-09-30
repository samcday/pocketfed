#!/usr/bin/python3
"""Identity and durable receipts for the 13 September daily clean-boot trace."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/var/tmp/sargo-fingerprint-loader-claim-20260913')
SERIAL = '994AY18RSD'
BOOT = '4deb54c7-8d28-4239-94c4-545f86b5678c'
RELEASE = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
DEPLOYMENT = 'd639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89'
UNITS = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
         'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service')
MASKS = ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
output = lambda argv: subprocess.check_output(argv, text=True).strip()


def guard():
    assert os.geteuid() == 0
    assert ROOT.resolve() == ROOT and ROOT.stat().st_uid == 0 and ROOT.stat().st_mode & 0o777 == 0o700
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert [a for a in Path('/proc/cmdline').read_text().split() if a.startswith('androidboot.serialno=')] == ['androidboot.serialno=' + SERIAL]
    assert os.uname().release == RELEASE and output(['getenforce']) == 'Enforcing'
    assert sha(Path('/etc/pam.d/phosh')) == '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
    for unit in MASKS:
        path = Path('/etc/systemd/system') / unit
        assert path.is_symlink() and path.readlink() == Path('/dev/null')
        assert output(['systemctl', 'show', unit.replace('@.', '@cleanboot-check.'),
                       '-p', 'ActiveState', '--value']) == 'inactive', unit
    for unit in UNITS:
        assert output(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive', unit
    status = json.loads(output(['rpm-ostree', 'status', '--json']))
    assert not status.get('transaction')
    assert [d['checksum'] for d in status['deployments'] if d.get('booted')] == [DEPLOYMENT]
    assert sha(ROOT / 'trace-core.py') == '7bd7352adfcdf6dc52db24eec5b9580ca85931a9a834bb49d50e1d8859125892'


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)
