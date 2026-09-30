#!/usr/bin/python3
"""Independently compare the MM baseline and complete fingerprint candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('evidence', type=Path)
parser.add_argument('--candidate-image', required=True)
args = parser.parse_args()
root = args.evidence
base = json.loads((root / 'base-facts-current.json').read_text())
candidate = json.loads((root / 'candidate-facts-current.json').read_text())
manifest = json.loads((root / 'image-context/inputs/manifest.json').read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
def rows(f):
    result = {}
    for line in f['packages_evra']:
        name, version = line.split('\t', 1)
        result.setdefault(name, []).append(version)
    return {n: sorted(v) for n, v in result.items()}
before, after = rows(base), rows(candidate)
expected, package_paths = {}, set()
for artifact in manifest['package_artifacts']:
    path = Path(artifact['path'])
    assert sha(path) == artifact['sha256']
    name, version = subprocess.check_output(['rpm', '-qp', '--qf',
        '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}', str(path)], text=True).split('\t')
    assert name not in expected
    expected[name] = [version]
    package_paths.update(subprocess.check_output(['rpm', '-qpl', str(path)], text=True).splitlines())
kernel_names = {n for n in before if n in {
    'kernel', 'kernel-core', 'kernel-modules', 'kernel-modules-core',
    'kernel-modules-extra', 'kernel-modules-internal', 'kernel-modules-extra-matched'}}
for name in kernel_names:
    expected[name] = ['0:7.1.2-0.pocketfed.sdm670.11.fc46.aarch64']
assert len(expected) == 14 + len(kernel_names)
assert all(after.get(n) == v for n, v in expected.items())
assert {n: v for n, v in before.items() if n not in expected} == {
    n: v for n, v in after.items() if n not in expected}, 'unrelated packages changed'
assert candidate['kernel_release'] == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert candidate['fingerprint_dt']['present']
assert candidate['boot']['outer_shim_sha256'] == base['boot']['outer_shim_sha256']
assert candidate['boot']['payloads_match_module_directory']
def boot_arguments(text):
    tokens = text.split()
    assert tokens[0] == '<S>' and tokens[-1] == '<E>'
    values = tokens[1:-1]
    assert len({v.split('=', 1)[0] for v in values}) == len(values), 'duplicate boot argument key'
    return sorted(values)
assert boot_arguments(candidate['boot']['cmdline']) == boot_arguments(base['boot']['cmdline']), 'boot arguments changed'
# The current finalizer emits inherited append-options before root arguments.
# This comparison permits ordering only for these verified distinct keys.
assert set(candidate['activation_masks'].values()) == {'/dev/null'}
assert not candidate['broker_runtime_state_present'] and not candidate['initialization_marker_present']
changes = {}
for group in ('authentication', 'systemd', 'files', 'selinux'):
    changes[group] = sorted(p for p in set(base[group]) | set(candidate[group])
                            if base[group].get(p) != candidate[group].get(p))
assert all(candidate['authentication'].get(p) == v for p, v in base['authentication'].items()), 'existing authentication configuration changed'
assert set(changes['authentication']) <= {'/usr/lib/pam.d/phosh-fingerprint', '/usr/lib/pam.d/fprintd'}
firmware_root = root / 'image-context/firmware'
firmware_paths = {
    '/usr/libexec/pocketfed-fingerprint-firmware': firmware_root / 'extract-firmware.py',
    '/usr/lib/systemd/system/pocketfed-fingerprint-firmware.service': firmware_root / 'pocketfed-fingerprint-firmware.service',
}
for path in firmware_root.glob('*.service.d/*'):
    firmware_paths['/usr/lib/systemd/system/' + str(path.relative_to(firmware_root))] = path
mask_paths = {'/etc/systemd/system/' + n for n in candidate['activation_masks']}
allowed = package_paths | set(firmware_paths) | mask_paths | {'/usr/libexec/pocketfed-verify-kernel'}
for group in ('files', 'systemd'):
    assert set(changes[group]) <= allowed, (group, set(changes[group]) - allowed)
for target, path in firmware_paths.items():
    group = 'systemd' if target.startswith('/usr/lib/systemd/') else 'files'
    assert candidate[group][target]['sha256'] == sha(path), target
policy_paths = {'/etc/selinux/targeted/policy/policy.35',
                '/etc/selinux/targeted/contexts/files/file_contexts',
                '/etc/selinux/targeted/contexts/files/file_contexts.bin'}
assert set(changes['selinux']) == policy_paths
report = candidate['upgrade_report']
assert report['base_image'] == manifest['base_image_id'] and report['services_activated'] is False
for name, target in [('policy.35', '/etc/selinux/targeted/policy/policy.35'),
                     ('file_contexts', '/etc/selinux/targeted/contexts/files/file_contexts')]:
    assert candidate['selinux'][target]['sha256'] == manifest['input_files'][name]
assert candidate['selinux']['/etc/selinux/targeted/contexts/files/file_contexts.bin']['sha256'] == report['file_contexts_bin_sha256']
result = {'status': 'independent image comparison passed; not staged or booted',
          'base_image': manifest['base_image_id'], 'candidate_image': args.candidate_image,
          'package_count': len(after), 'expected_package_changes': expected,
          'preserved_modem_packages': {n: after[n] for n in ('ModemManager', 'ModemManager-glib', 'libqmi', 'libqmi-utils', '81voltd', 'gtk4')},
          'preserved': ['all unrelated package versions', 'existing authentication and PIN files',
                        'boot shim and arguments', 'unrelated service units'],
          'changes': changes,
          'initramfs_module_changes': {'added': sorted(set(candidate['initramfs_modules']) - set(base['initramfs_modules'])),
                                     'removed': sorted(set(base['initramfs_modules']) - set(candidate['initramfs_modules']))},
          'evidence_sha256': {n: sha(root / n) for n in ('base-facts-current.json', 'candidate-facts-current.json')},
          'comparator_sha256': sha(Path(__file__))}
(root / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: result[k] for k in ('status', 'package_count', 'preserved_modem_packages', 'initramfs_module_changes')}, indent=2))
