#!/usr/bin/python3
"""Stage one temporary traced libfprint binding on the identified daily phone.

No enrollment/verification/credential operations and no reboot. The binding
is in /run and expires on reboot. Installed distribution files stay intact.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SERIAL = '994AY18RSD'
BOOT = '51d59842-0056-46a5-a417-532ef194ad54'
PIN_HASH = '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
BASE_LIBRARY_HASH = '71ea0aea2c8d4903126a35fe1620d6fa645d3599cdcde2a0ec34a2166737fedc'
ROOT = Path('/var/tmp/sargo-fingerprint-mm-20260912/driver-trace-v2')
TARGET = Path('/usr/lib64/libfprint-2.so.2.0.0')
PRIVATE_LIBRARY = Path('/usr/local/lib64/pocketfed-fingerprint-trace-20260912/libfprint-2.so.2.0.0')
DROPIN = Path('/run/systemd/system/fprintd.service.d/99-call-trace.conf')


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
    assert ROOT.is_dir() and not ROOT.is_symlink() and ROOT.stat().st_uid == 0
    assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')] == ['androidboot.serialno=' + SERIAL]
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert sha(Path('/etc/pam.d/phosh')) == PIN_HASH
    assert sha(TARGET) == BASE_LIBRARY_HASH
    assert run('rpm', '-q', 'libfprint') == 'libfprint-1.94.100-1.6.pocketfed.fc46.aarch64'
    assert run('getenforce') == 'Enforcing'
    socket = Path('/run/systemd/system/phosh-fingerprint-auth.socket')
    assert socket.is_symlink() and socket.resolve() == Path('/dev/null')
    assert run('systemctl', 'show', 'phosh-fingerprint-auth.socket', '-p', 'ActiveState', '--value') == 'inactive'
    for unit in ['fprintd.service', 'qsee-supplicant.service', 'pocketfed-fpc-auth.service']:
        assert run('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
    manifest = json.loads((ROOT / 'bundle.json').read_text())
    for name, expected in manifest['files'].items():
        assert Path(name).name == name
        path = ROOT / name
        assert path.is_file() and not path.is_symlink() and path.stat().st_uid == 0
        assert not path.stat().st_mode & 0o022
        assert sha(path) == expected
    assert manifest['arm64_tests_passed'] and manifest['host_boundary_tests_passed']
    assert not PRIVATE_LIBRARY.exists() and not DROPIN.exists()
    with (ROOT / 'install-attempt.json').open('x') as f:
        json.dump({'serial': SERIAL, 'boot_id': BOOT, 'runtime_dropin': str(DROPIN)}, f)
        f.write('\n')
    PRIVATE_LIBRARY.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(ROOT / TARGET.name, PRIVATE_LIBRARY)
    PRIVATE_LIBRARY.chmod(0o644)
    subprocess.run(['chcon', '--reference=' + str(TARGET), str(PRIVATE_LIBRARY)], check=True)
    assert sha(PRIVATE_LIBRARY) == manifest['files'][TARGET.name]
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    with DROPIN.open('x') as f:
        f.write('[Service]\nBindReadOnlyPaths=' + str(PRIVATE_LIBRARY) + ':' + str(TARGET) + '\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    binds = run('systemctl', 'show', 'fprintd.service', '-p', 'BindReadOnlyPaths', '--value')
    assert str(PRIVATE_LIBRARY) + ':' + str(TARGET) in binds, binds
    subprocess.run(['systemd-run', '--unit=pocketfed-fpc-trace-uart-20260912',
                    '--property=StandardOutput=append:/dev/ttyMSM0', '--property=StandardError=journal',
                    '/usr/bin/journalctl', '--follow', '--boot', '--lines=0', '--no-pager',
                    '--output=short-monotonic', '--unit=fprintd.service',
                    '--unit=pocketfed-fpc-claim-only-20260912.service'], check=True)
    assert run('systemctl', 'is-active', 'pocketfed-fpc-trace-uart-20260912.service') == 'active'
    assert sha(Path('/etc/pam.d/phosh')) == PIN_HASH and sha(TARGET) == BASE_LIBRARY_HASH
    record = {'serial': SERIAL, 'boot_id': BOOT, 'library_sha256': sha(PRIVATE_LIBRARY),
              'runtime_dropin': str(DROPIN), 'pin_unchanged': True,
              'distribution_library_unchanged': True, 'fingerprint_scan_started': False,
              'restore': 'After fprintd is inactive, remove only the runtime 99-call-trace.conf drop-in and run systemctl daemon-reload. The Phosh scan pause is separate.'}
    with (ROOT / 'installed.json').open('x') as f:
        json.dump(record, f, indent=2)
        f.write('\n')
    with open('/dev/ttyMSM0', 'w') as uart:
        uart.write('POCKETFED_FPC_TRACE_STAGED_' + SERIAL + '_' + BOOT + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
