#!/usr/bin/python3
"""Reject unrelated package/policy changes in the local Sargo fingerprint image."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shlex

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('base', type=Path)
parser.add_argument('candidate', type=Path)
parser.add_argument('runtime_manifest', type=Path)
parser.add_argument('policy_manifest', type=Path)
args = parser.parse_args()
base = json.loads(args.base.read_text())
candidate = json.loads(args.candidate.read_text())
expected = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert candidate['kernel_release'] == expected
assert candidate['fingerprint_dt']['present']
assert candidate['initramfs_module_release_verified']
assert candidate['boot']['payloads_match_module_directory']
assert candidate['boot']['outer_shim_sha256'] == base['boot']['outer_shim_sha256']
base_args, candidate_args = [shlex.split(x['boot']['cmdline']) for x in (base, candidate)]
assert candidate_args[0] == '<S>' and candidate_args[-1] == '<E>'
assert Counter(candidate_args) == Counter(base_args), 'boot command line changed'
for token in ['root=LABEL=pfroot', 'rootfstype=ext4', 'rw', 'rootwait', 'ostree=true']:
    assert candidate_args.count(token) == 1, token
for key in ['root', 'rootfstype', 'ostree']:
    assert sum(token.startswith(key + '=') for token in candidate_args) == 1, key
assert candidate['initramfs_inventory'] == base['initramfs_inventory']
policy_manifest = json.loads(args.policy_manifest.read_text())
expected_policy = dict(base['selinux_policy'])
for record in policy_manifest['files'].values():
    assert base['selinux_policy'][record['target']] == record['base']
    expected_policy[record['target']] = record['candidate']
assert candidate['selinux_policy'] == expected_policy, 'policy differs from independently validated module integration'
assert candidate['initial_activation']['broker_present']
assert not candidate['initial_activation']['broker_runtime_state_present']
assert not candidate['initial_activation']['database_init_marker_present']
assert not candidate['initial_activation']['build_only_helpers_present']
for name in ['dtb_sha256', 'canonical_kernel_sha256', 'initramfs_sha256']:
    assert candidate['boot'][name] != base['boot'][name], name


def packages(lines):
    result = {}
    for line in lines:
        name, version = line.split('\t', 1)
        result.setdefault(name, []).append(version)
    return {name: sorted(versions) for name, versions in result.items()}


before, after = packages(base['packages_evra']), packages(candidate['packages_evra'])
runtime = json.loads(args.runtime_manifest.read_text())['rpms']
selected = {row['name']: row['evra'] for row in runtime}
assert len(runtime) == len(selected) == 19
assert set(selected) == {'libfprint', 'libfprint-fpc-qsee', 'fprintd', 'fprintd-pam',
    'fpc-qsee-probe', 'qsee-supplicant', 'phosh', 'libphosh', 'phosh-fingerprint-auth',
    'gnome-control-center', 'gnome-control-center-filesystem', 'tailscale',
    'feedbackd-device-themes', 'lpa-gtk', 'python3-cairo', 'python3-gobject', 'python3-gobject-base',
    'pocketfed-fpc-auth', 'pocketfed-fpc-selinux'}
for name, evra in selected.items():
    assert after.get(name) == [evra], (name, after.get(name), evra)
kernel = {'kernel', 'kernel-core', 'kernel-modules', 'kernel-modules-core',
          'kernel-modules-extra', 'kernel-modules-internal', 'kernel-modules-extra-matched'}
allowed = kernel | {'phosh', 'libphosh', 'gnome-control-center', 'gnome-control-center-filesystem'}
changed = {name: [value, after.get(name)] for name, value in before.items() if after.get(name) != value}
assert not set(changed) - allowed, changed
assert kernel & before.keys() == kernel & after.keys()
assert all(after[name] == ['0:' + expected] for name in kernel & after.keys())
extras = {'tailscale': '1.98.8-1.fc45.aarch64',
          'feedbackd-device-themes': '0.8.9-1.fc46.noarch',
          'lpa-gtk': '0.4-1.4.pocketfed.fc46.noarch',
          'python3-cairo': '1.28.0-8.fc45.aarch64',
          'python3-gobject': '3.57.1-6.fc46.aarch64',
          'python3-gobject-base': '3.57.1-6.fc46.aarch64'}
for name, version in extras.items():
    assert after.get(name) == ['0:' + version], (name, after.get(name), version)
for name in ['81voltd', 'ModemManager', 'gtk4']:
    assert after[name] == before[name]
for path, info in base['files'].items():
    if path == '/usr/libexec/pocketfed-verify-kernel':
        continue  # Independently checked by recipe: only .8/.9 -> .11 token.
    assert candidate['files'].get(path) == info, path
for path, info in base['authentication_and_device_policy'].items():
    assert candidate['authentication_and_device_policy'].get(path) == info, path
new_pam = {path: info for path, info in candidate['authentication_and_device_policy'].items()
           if path not in base['authentication_and_device_policy']}
assert new_pam == {'/usr/lib/pam.d/phosh-fingerprint': {
    'bytes': 415, 'sha256': '9c66c88c428cb55a06bb2094bae487b447db26ab9a81c7a19bbe0b9426485c84'}}, new_pam
masks = {'/etc/systemd/system/' + name: '/dev/null' for name in
    ['fprintd.service', 'qsee-supplicant.service', 'phosh-fingerprint-auth.socket',
     'pocketfed-fpc-auth.socket', 'pocketfed-fpc-provision@.service']}
assert candidate['system_enablement'] == {**base['system_enablement'], **masks}
for path, info in base['systemd_policy_files'].items():
    assert candidate['systemd_policy_files'].get(path) == info, path
new_units = {path for path in candidate['systemd_policy_files'] if path not in base['systemd_policy_files']}
expected_units = set(masks) | {'/usr/lib/systemd/' + name for name in [
    'system/qsee-app-loader@.service', 'system/qsee-shared-loader@.service',
    'system/qsee-supplicant.service', 'system/phosh-fingerprint-auth.socket',
    'system/pocketfed-fpc-auth.service', 'system/pocketfed-fpc-auth.socket',
    'system/pocketfed-fpc-provision@.service',
    'system/phosh-fingerprint-auth@.service', 'system/fprintd.service',
    'system/tailscaled.service', 'user/tailscale-systray.service',
    'system/pocketfed-fingerprint-firmware.service',
    'system/fprintd.service.d/90-fpc-qsee.conf',
    'system/qsee-app-loader@fpctzappfingerprint.service.d/90-common-library.conf',
    'system/qsee-shared-loader@cmnlib64.service.d/90-firmware.conf']}
assert new_units == expected_units, {'unexpected': sorted(new_units - expected_units),
                                     'missing': sorted(expected_units - new_units)}
# Independently checked against the selected signed RPM payloads and the three
# reviewed firmware preparation source files. Presence alone must not accept a
# changed activation dependency, executable, identity, or sandbox setting.
unit_content = {
    'system/pocketfed-fpc-auth.service': (1614, 'ad5e1f156d4764896ea6e3b9007368d2659d8a0b2d9b93ee6e1ebd696ad192fe'),
    'system/pocketfed-fpc-auth.socket': (487, '86c119a57bd60e873ec1caaf9b56377d042ba0396713cb3d46be3a83af28fe55'),
    'system/pocketfed-fpc-provision@.service': (1612, 'b512974bbffba761e5b1f2a49519badcb820b6841a3ba23ac910613414b0e6d3'),
    'system/fprintd.service': (928, 'da6722b0404c3a8e4ab3b3a6247be0bf9f0e8bf10f99e9f9457004f8a202c050'),
    'system/fprintd.service.d/90-fpc-qsee.conf': (1061, '6960506693680e26f2f2e4d6099a51c59d142eccb1f2d7d94f654a90b8ea620b'),
    'system/phosh-fingerprint-auth.socket': (249, 'bc0a829f21980deedd2619699efe0994393034b16984b01dc28bd613b773958b'),
    'system/phosh-fingerprint-auth@.service': (281, 'bf6bb1e4639098fbd183e48faf12ec4b143d6469331e048368ec624b1a238ea4'),
    'system/pocketfed-fingerprint-firmware.service': (773, 'ddc5f04f5bf1e62276ed2c1d84129a86b1c65240a03c88ec0b62844ab7a29990'),
    'system/qsee-app-loader@.service': (762, 'b1e45f79acb8b055eebdddaf0659946ed2f258292818bac2c2978c9842467832'),
    'system/qsee-app-loader@fpctzappfingerprint.service.d/90-common-library.conf': (94, '12a346e72dafe5d4b3536439dd7663a3b56f2ddb30b3a97ae46256638e1f18a7'),
    'system/qsee-shared-loader@.service': (673, 'ea1e1396e4e4e2bcced020ce5b42e89ead263ab830724688587a63e3f839c0de'),
    'system/qsee-shared-loader@cmnlib64.service.d/90-firmware.conf': (148, '8640f5fe3061e9d269af3cce51d04301ee2b26710b81cb9585161b52abaa9153'),
    'system/qsee-supplicant.service': (776, '3c8a1a7be718a400bfab842ac238fcc7e12206a7e5355956b8e43fcb5e074563'),
    'system/tailscaled.service': (1198, '664c6fa3a92c74f1c30c03ce0910c756d228d0612f23f656bcf6cc6654270e9c'),
    'user/tailscale-systray.service': (257, 'fd9802a87d678d32e7c68dc537cbeb6107fe604f7e1dc9b2d3390d36c18e37b7')}
assert {'/usr/lib/systemd/' + name for name in unit_content} == expected_units - set(masks)
for name, (size, digest) in unit_content.items():
    assert candidate['systemd_policy_files']['/usr/lib/systemd/' + name] == {
        'bytes': size, 'sha256': digest}, name
added = {name: value for name, value in after.items() if name not in before}
assert set(added) == set(selected) - set(before), added
assert after['pocketfed-fpc-auth'] == ['0:0.1.0-0.2.pocketfed.fc46.aarch64']
assert after['pocketfed-fpc-selinux'] == ['0:0.1.0-0.1.pocketfed.fc46.noarch']
new_state = {
    '/var/cache/tailscale': {'mode': '0o600', 'type': 'directory'},
    '/var/lib/tailscale': {'mode': '0o600', 'type': 'directory'},
    '/var/lib/fprint': {'mode': '0o700', 'type': 'directory'},
    '/var/lib/fprint/fpc-qsee': {'mode': '0o700', 'type': 'directory'}}
assert candidate['mutable_state_paths'] == {**base['mutable_state_paths'], **new_state}, \
    'unexpected mutable state paths or permissions'
print(json.dumps({'result': 'passed', 'kernel_release': expected,
                  'boot_image_bytes': candidate['boot']['bytes'],
                  'unchanged_outer_abl_shim': True, 'new_dtb_verified': True,
                  'all_unrelated_base_packages_unchanged': True,
                  'existing_policy_files_and_enablement_preserved': True,
                  'selinux_matches_reviewed_module_integration': True,
                  'initramfs_inventory_identical_to_working_base': True,
                  'boot_critical_drivers_verified': candidate['initramfs_inventory']['critical_drivers_present'],
                  'added_mutable_state_paths': {k:v for k,v in candidate['mutable_state_paths'].items()
                                                if k not in base['mutable_state_paths']},
                  'live_overlay_versions_preserved': extras,
                  'selected_runtime_evr_as_installed': selected,
                  'changed_packages': changed, 'added_packages': added}, indent=2, sort_keys=True))
