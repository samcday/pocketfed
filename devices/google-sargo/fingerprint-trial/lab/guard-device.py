#!/usr/bin/python3
"""Identity and inactivity guard for a disposable test-sargo receiver trial."""
import json
from pathlib import Path
import subprocess

cmdline = Path('/proc/cmdline').read_text().split()
assert 'androidboot.serialno=99NAY1AZG1' in cmdline
assert 'pocketfed.root_mode=usb' in cmdline
assert any(x.startswith('pocketfed.liveboot=sargo-fingerprint-lab-') for x in cmdline)
assert subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '/'], text=True).strip() == 'overlay'
assert b'google,sargo' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
assert Path('/sys/block/mmcblk0/device/type').read_text().strip() == 'MMC'
for unit in ('qsee-supplicant.service', 'fprintd.service', 'pocketfed-fpc-auth.service',
             'qsee-shared-loader@cmnlib64.service', 'qsee-app-loader@fpctzappfingerprint.service'):
    state = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID'], text=True)
    assert set(state.splitlines()) == {'ActiveState=inactive', 'MainPID=0'}, unit
report = json.loads(Path('/run/pocketfed-fingerprint-lab/inspection.json').read_text())
assert report['serial'] == '99NAY1AZG1' and report['secure_calls'] is False
assert report['firmware']['metadata']['vendor_build'] == 'google/sargo/sargo:12/SP2A.220505.002/8353555:user/release-keys'
