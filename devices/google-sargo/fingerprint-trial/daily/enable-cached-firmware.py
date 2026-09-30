#!/usr/bin/python3
"""Correct the old installed firmware unit after its pre-exec namespace failure.

Reuse the existing fully verified stock cache. No firmware is copied from the
lab, no vendor mapping is created, and no secure application is opened here.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import stat
import subprocess

ROOT = Path('/var/tmp/sargo-fingerprint-services-20260912')
HELPER_SHA = 'cc5e2a6917f3a7ae63f05c0008bfc9928738e64e06fc9800ad7ae5e49e4e6787'
OLD_SHA = 'a4f4271ad3348be98acafe336926e10fd38dbfa79c06c42a7641a8eb4697c8a0'
DROPIN = '''[Service]
ExecStart=
ExecStart=/usr/bin/python3 /usr/local/libexec/pocketfed-fingerprint-firmware --ensure
ReadOnlyPaths=
ReadOnlyPaths=-/dev/mapper/vendor_b
'''


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.getuid() == os.geteuid() == 0
    assert [s for s in Path('/proc/cmdline').read_text().split()
            if s.startswith('androidboot.serialno=')] == ['androidboot.serialno=994AY18RSD']
    expected = json.loads((ROOT / 'staged-inspection.json').read_text())
    state = json.loads(out('rpm-ostree', 'status', '--json'))
    assert state['transaction'] is None and not any(d.get('staged') for d in state['deployments'])
    assert next(d for d in state['deployments'] if d['booted'])['checksum'] == expected['staged_checksum']
    assert out('getenforce') == 'Enforcing'
    assert sha(Path('/etc/selinux/targeted/policy/policy.35')) == expected['policy_sha256']
    for unit in ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
                 'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service',
                 'fprintd.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service',
                 'phosh-fingerprint-auth.socket'):
        assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
    unit = 'pocketfed-fingerprint-firmware.service'
    assert out('systemctl', 'show', unit, '-p', 'ExecMainStatus', '--value') == '226'
    assert out('systemctl', 'show', unit, '-p', 'Result', '--value') == 'exit-code'
    assert (ROOT / 'startup-attempt.json').is_file()
    assert sha(Path('/usr/libexec/pocketfed-fingerprint-firmware')) == OLD_SHA
    source = ROOT / 'cached-firmware.py'
    st = source.lstat()
    assert stat.S_ISREG(st.st_mode) and st.st_uid == st.st_gid == 0 and not st.st_mode & 0o022
    assert sha(source) == HELPER_SHA
    spec = importlib.util.spec_from_file_location('cached_firmware', source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.validate_device()
    assert Path('/usr/lib/firmware/updates').resolve() == helper.DESTINATION
    manifest = json.loads(helper.MANIFEST.read_text())
    payloads = helper.cached_payloads(helper.DESTINATION, manifest)
    assert payloads is not None, 'existing verified cache is required; no extraction fallback here'
    count = len(payloads)
    del payloads
    destination = Path('/usr/local/libexec/pocketfed-fingerprint-firmware')
    directory = Path('/etc/systemd/system') / (unit + '.d')
    override = directory / '99-verified-cache.conf'
    assert not destination.exists() and not destination.is_symlink()
    assert not override.exists() and not override.is_symlink()
    with (ROOT / 'cached-firmware-correction.json').open('x') as f:
        json.dump({'helper_sha256': HELPER_SHA, 'cache_files_verified': count,
                   'original_namespace_exit': 226, 'credential_operation': False,
                   'startup_attempt_preserved': True}, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    for parent in (destination.parent, directory):
        parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        st = parent.lstat()
        assert stat.S_ISDIR(st.st_mode) and st.st_uid == st.st_gid == 0 and not st.st_mode & 0o022
    with destination.open('xb') as f:
        f.write(source.read_bytes())
        f.flush()
        os.fsync(f.fileno())
    destination.chmod(0o755)
    with override.open('x') as f:
        f.write(DROPIN)
        f.flush()
        os.fsync(f.fileno())
    override.chmod(0o644)
    subprocess.run(['restorecon', str(destination), str(override)], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'reset-failed', unit], check=True)
    print(json.dumps({'status': 'persistent cache helper and override installed',
                      'cache_files_verified': count, 'credential_operation': False}))


if __name__ == '__main__':
    main()
