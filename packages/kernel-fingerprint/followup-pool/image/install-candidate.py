#!/usr/bin/python3
"""Install only the recorded .12 kernel set and Settings 1.2 in a local image."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

INPUT = Path('/run/fingerprint-candidate')
REPORT = Path('/usr/share/pocketfed/fingerprint-trial/kernel12-upgrade.json')
FORMAT = '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'
KERNEL = {'kernel', 'kernel-core', 'kernel-modules', 'kernel-modules-core'}
SETTINGS = {'gnome-control-center', 'gnome-control-center-filesystem'}
MASKS = ('fprintd.service', 'qsee-supplicant.service', 'pocketfed-fpc-auth.socket',
         'pocketfed-fpc-provision@.service', 'phosh-fingerprint-auth.socket')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packages(*args):
    rows = subprocess.check_output(['rpm', *args, '--qf', FORMAT], text=True).splitlines()
    result = {}
    for row in rows:
        name, version = row.split('\t')
        result.setdefault(name, []).append(version)
    return {name: sorted(versions) for name, versions in result.items()}


def protected():
    roots = ('/etc/pam.d', '/usr/lib/pam.d', '/etc/authselect', '/etc/phrog',
             '/etc/greetd', '/etc/dracut.conf.d', '/etc/selinux/targeted',
             '/etc/systemd/system', '/etc/systemd/user', '/usr/lib/systemd/system',
             '/usr/lib/systemd/user', '/usr/share/plymouth', '/usr/lib/ostree-boot')
    paths = {p for root in roots for p in Path(root).rglob('*')
             if p.is_file() or p.is_symlink()}
    paths.update(Path(p) for p in ('/usr/libexec/phosh', '/usr/libexec/phosh-fingerprint-worker',
                 '/usr/libexec/phosh-fingerprint-auth', '/usr/bin/pocketfed-fpc-auth',
                 '/usr/bin/qsee-sargo-rpmb', '/usr/bin/qsee-supplicant'))
    return {str(p): {'symlink': os.readlink(p)} if p.is_symlink()
            else {'sha256': sha(p)} for p in sorted(paths)}


def main():
    assert Path('/run/.containerenv').exists() or Path('/.dockerenv').exists()
    assert not REPORT.exists()
    manifest = json.loads((INPUT / 'manifest.json').read_text())
    files = {str(p.relative_to(INPUT)) for p in INPUT.rglob('*') if p.is_file()}
    assert files == set(manifest['files']) | {'manifest.json'}
    for name, digest in manifest['files'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        path = INPUT / name
        assert not path.is_symlink() and sha(path) == digest, name
    before = packages('-qa')
    assert before == manifest['base_packages'], 'Unexpected image package inventory'
    assert set(before) & KERNEL == KERNEL
    assert all(before[n] == ['0:7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'] for n in KERNEL)
    assert before['gnome-control-center'] == ['0:51~rc.1-1.1.fingerprint.fc46.aarch64']
    assert before['gnome-control-center-filesystem'] == ['0:51~rc.1-1.1.fingerprint.fc46.noarch']
    for unit in MASKS:
        assert os.readlink('/etc/systemd/system/' + unit) == '/dev/null'
    for path in ('/var/lib/pocketfed-fpc-auth', '/run/pocketfed-fpc-auth',
                 '/var/lib/fprint/fpc-qsee/initialize-empty'):
        assert not Path(path).exists(), path
    keep = protected()
    assert keep == manifest['protected_files'], 'Unexpected boot, policy or authentication files'
    kernel = sorted(str(p) for p in (INPUT / 'kernel-rpms').glob('*.rpm'))
    settings = sorted(str(p) for p in (INPUT / 'settings-rpms').glob('*.rpm'))
    expected = packages('-qp', *kernel, *settings)
    assert set(expected) == KERNEL | SETTINGS
    assert all(expected[n] == ['0:7.1.2-0.pocketfed.sdm670.12.fc46.aarch64'] for n in KERNEL)
    assert expected['gnome-control-center'] == ['0:51~rc.1-1.2.fingerprint.fc46.aarch64']
    assert expected['gnome-control-center-filesystem'] == ['0:51~rc.1-1.2.fingerprint.fc46.noarch']
    subprocess.run(['/tmp/install-fingerprint-kernel'], check=True)
    # These two unsigned local builds are verified by their frozen SHA-256
    # records above. Retain RPM dependency and payload digest checks.
    subprocess.run(['rpm', '-Uvh', '--nosignature', '--test', *settings], check=True)
    subprocess.run(['rpm', '-Uvh', '--nosignature', *settings], check=True)
    after = packages('-qa')
    assert all(after.get(n) == v for n, v in expected.items())
    assert {n: v for n, v in before.items() if n not in expected} == {
        n: v for n, v in after.items() if n not in expected}
    assert protected() == keep, 'Protected file changed'
    assert not subprocess.check_output(['modinfo', '-k',
        '7.1.2-0.pocketfed.sdm670.12.fc46.aarch64', '-p', 'qseecomtee']).strip()
    REPORT.write_text(json.dumps({'base_image': manifest['base_image'],
        'manifest_sha256': sha(INPUT / 'manifest.json'), 'updated_packages': expected,
        'protected_file_count': len(keep), 'protected_files_unchanged': True,
        'unrelated_packages_unchanged': True, 'services_activated': False,
        'copr_build': 10980882}, indent=2) + '\n')
    print('PASS: complete .12 kernel and Settings 1.2; protected files and unrelated packages unchanged')


if __name__ == '__main__':
    main()
