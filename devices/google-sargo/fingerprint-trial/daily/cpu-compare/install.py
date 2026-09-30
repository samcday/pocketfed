#!/usr/bin/python3
"""Stage the exact probe and two inactive runtime units; do not open the sensor."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/var/tmp/sargo-fingerprint-cpu-compare-20260913')
assert Path(__file__).resolve().parent == ROOT
sys.path.insert(0, str(ROOT))
import controller as c

os.umask(0o077)
manifest = c.guard(check_installed_binary=False)
assert not os.path.lexists(c.BINARY)
units = [Path('/run/systemd/system') / f'pocketfed-fpc-cpu{cpu}-20260913.service' for cpu in (7, 1)]
assert all(not os.path.lexists(unit) for unit in units)
c.save(ROOT / 'install-attempt.json', {'serial': c.SERIAL, 'boot_id': c.BOOT,
                                    'probe_sha256': manifest['probe_sha256']})
with c.BINARY.open('xb') as stream:
    stream.write((ROOT / 'initialize-once').read_bytes())
    stream.flush()
    os.fsync(stream.fileno())
c.BINARY.chmod(0o755)
subprocess.run(['restorecon', str(c.BINARY)], check=True)
for cpu, unit in zip((7, 1), units):
    with unit.open('x') as stream:
        stream.write(f'''[Unit]
Description=One guarded daily fingerprint initialization on CPU {cpu}
ConditionKernelCommandLine=androidboot.serialno={c.SERIAL}
[Service]
Type=exec
ExecStart=/usr/bin/python3 -u {ROOT}/controller.py --cpu={cpu}
Restart=no
TimeoutStartSec=infinity
TimeoutStopSec=infinity
LimitCORE=0
UMask=0077
StandardInput=null
StandardOutput=append:/dev/ttyMSM0
StandardError=append:/dev/ttyMSM0
''')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
c.guard()
for unit in units:
    assert c.output(['systemctl', 'show', unit.name, '-p', 'ActiveState', '--value']) == 'inactive'
c.save(ROOT / 'installed.json', {'serial': c.SERIAL, 'boot_id': c.BOOT,
                                'probe_sha256': manifest['probe_sha256'],
                                'units': [p.name for p in units], 'sensor_opened': False})
print('Daily CPU comparison installed; both trial units inactive, fingerprint masks preserved.')
