#!/usr/bin/python3
"""Open and close the already-enrolled daily sensor without starting a scan.

Run only after the traced library and UART journal relay are verified. Claim
opens the sensor, initializes the TA and loads the existing Linux database.
It never calls enrollment, verification, deletion or credential recovery.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

SERIAL = '994AY18RSD'
BOOT = '51d59842-0056-46a5-a417-532ef194ad54'
PIN_HASH = '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'


def main():
    assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')] == ['androidboot.serialno=' + SERIAL]
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert hashlib.sha256(Path('/etc/pam.d/phosh').read_bytes()).hexdigest() == PIN_HASH
    assert subprocess.check_output(['getenforce'], text=True).strip() == 'Enforcing'
    assert Path('/run/systemd/system/phosh-fingerprint-auth.socket').is_symlink()
    assert Path('/run/systemd/system/phosh-fingerprint-auth.socket').resolve() == Path('/dev/null')
    root = Path(__file__).resolve().parent
    installed = json.loads((root / 'installed.json').read_text())
    assert installed['boot_id'] == BOOT and installed['serial'] == SERIAL
    assert subprocess.check_output(['systemctl', 'is-active', 'pocketfed-fpc-trace-uart-20260912.service'], text=True).strip() == 'active'
    assert not list(Path('/var/lib/fprint/fpc-qsee').glob('initialize-empty'))
    assert subprocess.run(['systemctl', 'is-active', '--quiet', 'fprintd.service']).returncode != 0
    client_manifest = json.loads((root / 'claim-client.json').read_text())
    client = Path('/usr/local/libexec/pocketfed-fpc-claim-only-20260912')
    assert hashlib.sha256(client.read_bytes()).hexdigest() == client_manifest['sha256']
    receipt = root / 'claim-only-attempt.json'
    with receipt.open('x') as f:
        json.dump({'boot_id': BOOT, 'serial': SERIAL, 'started_at': time.time(),
                   'operations': ['GetDefaultDevice', 'ListEnrolledFingers', 'Claim', 'Release'],
                   'physical_touch_requested': False}, f, indent=2)
        f.write('\n')
    subprocess.run(['systemctl', 'start', 'fprintd.service'], check=True)
    pid = int(subprocess.check_output(['systemctl', 'show', 'fprintd.service', '-p', 'MainPID', '--value'], text=True))
    assert pid > 1
    mapped = Path(f'/proc/{pid}/root/usr/lib64/libfprint-2.so.2.0.0')
    assert hashlib.sha256(mapped.read_bytes()).hexdigest() == installed['library_sha256']
    subprocess.run([str(client)], check=True)
    with (root / 'claim-only-result.json').open('x') as f:
        json.dump({'boot_id': BOOT, 'result': 'claim and release completed',
                   'existing_right_index_checked': True, 'capture_started': False}, f, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
