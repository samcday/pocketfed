#!/usr/bin/python3
"""Complete the approved native attempt after a proven pre-exec launch failure.

The original unit exited 203/EXEC without running C or creating a new receipt.
The identical binary then returned 2 for an invalid argument under the same
sandbox from /usr/local/libexec. Preserve both results; change only ExecStart's
path. A C-level attempt or any other original failure categorically forbids this.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import subprocess

ROOT = Path('/var/tmp/sargo-fingerprint-services-20260912')
BUNDLE = ROOT / 'recovery-bundle'
UNIT = 'pocketfed-fpc-storage-recovery-once.service'
DESTINATION = Path('/usr/local/libexec/pocketfed-fpc-storage-recovery-20260912')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.getuid() == os.geteuid() == 0
    assert sha(BUNDLE / 'manifest.json') == '392c66aefbf6236f32fc6e45a9aa94a46738d691c44d2eb6d3e85d45674e4c53'
    spec = importlib.util.spec_from_file_location('frozen_launcher', BUNDLE / 'launch-recovery.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    manifest = launcher.check_bundle(BUNDLE)
    assert [s for s in Path('/proc/cmdline').read_text().split()
            if s.startswith('androidboot.serialno=')] == ['androidboot.serialno=994AY18RSD']
    state = json.loads(out('rpm-ostree', 'status', '--json'))
    assert state['transaction'] is None and not any(d.get('staged') for d in state['deployments'])
    assert next(d for d in state['deployments'] if d['booted'])['checksum'] == manifest['booted_checksum']
    assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    assert out('getenforce') == 'Enforcing'
    assert sha(Path('/etc/selinux/targeted/policy/policy.35')) == manifest['policy_sha256']
    assert out('systemctl', 'show', UNIT, '-p', 'ExecMainStatus', '--value') == '203'
    assert out('systemctl', 'show', UNIT, '-p', 'ExecMainCode', '--value') == '1'
    assert out('systemctl', 'show', UNIT, '-p', 'ActiveState', '--value') == 'failed'
    assert sha(Path('/run/systemd/system') / UNIT) == manifest['files'][UNIT]
    assert out('systemctl', 'show', 'pocketfed-fpc-recovery-exec-preflight.service',
               '-p', 'ExecMainStatus', '--value') == '2'
    assert sha(DESTINATION) == manifest['binary_sha256']
    assert os.getxattr(DESTINATION, 'security.selinux').rstrip(b'\0') == b'system_u:object_r:pocketfed_fpc_auth_exec_t:s0'
    for unit in ('fprintd.service', 'pocketfed-fpc-auth.socket',
                 'pocketfed-fpc-auth.service', 'phosh-fingerprint-auth.socket'):
        assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive'
    for unit in ('fprintd.service', 'pocketfed-fpc-auth.socket', 'phosh-fingerprint-auth.socket'):
        assert out('systemctl', 'show', unit, '-p', 'LoadState', '--value') == 'masked'
    for unit in ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
                 'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service'):
        assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'active'
        assert out('systemctl', 'show', unit, '-p', 'NRestarts', '--value') == '0'
    pid = int(out('systemctl', 'show', 'qsee-supplicant.service', '-p', 'MainPID', '--value'))
    assert os.readlink(f'/proc/{pid}/exe') == '/usr/bin/qsee-sargo-rpmb'
    assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') == [b'/usr/bin/qsee-sargo-rpmb', b'--serve-authenticated', b'']
    assert sha(Path('/usr/bin/qsee-sargo-rpmb')) == '300662ae47ff9bcdac15c1f89413b5a1f169e55ff417d92b2c5deb49d158ffbb'
    assert out('systemctl', 'show', 'qsee-supplicant.service', '-p', 'Restart', '--value') == 'no'
    store = Path('/var/lib/pocketfed-fpc-auth')
    files = {'.lock': 0, 'uid-1000.intent': 160, 'uid-1000.first-recovery-attempt': 132}
    assert {p.name for p in store.iterdir()} == set(files)
    for name, size in files.items():
        launcher.regular(store / name, size)
    assert {str(p.relative_to('/var/lib/fprint')) for p in Path('/var/lib/fprint').rglob('*')} == {'fpc-qsee', 'fpc-qsee/device.lock'}
    launcher.regular(Path('/var/lib/qsee-supplicant/pocketfed/fpc-sargo-v1.db'), 77)
    evidence = {'prior_unit_exit': 203, 'invalid_argument_preflight_exit': 2,
                'binary_sha256': manifest['binary_sha256'], 'previous_native_attempt': False,
                'correction': 'ExecStart path only; original unit and failed-launch evidence retained',
                'native_retry': False}
    with (ROOT / 'recovery-exec-correction.json').open('x') as f:
        json.dump(evidence, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    directory = Path('/run/systemd/system') / (UNIT + '.d')
    directory.mkdir(mode=0o755)
    with (directory / '90-installed-executable.conf').open('x') as f:
        f.write('[Service]\nExecStart=\nExecStart=' + str(DESTINATION) +
                ' recover-storage-sam-sargo-994AY18RSD-uid-1000\n')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # Reset only the proven pre-exec failure. StartLimitBurst remains 1;
    # the unchanged C program exclusively creates the durable native receipt.
    subprocess.run(['systemctl', 'reset-failed', UNIT], check=True)
    subprocess.run(['systemctl', 'start', UNIT], check=True)
    print('Approved native recovery completed; inspect durable result metadata.')


if __name__ == '__main__':
    main()
