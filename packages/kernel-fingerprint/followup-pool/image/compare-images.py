#!/usr/bin/python3
"""Compare independently inspected .11 and .12 images before device staging."""
import argparse
import hashlib
import json
from pathlib import Path

KERNEL = {'kernel', 'kernel-core', 'kernel-modules', 'kernel-modules-core'}


def packages(facts):
    result = {}
    for row in facts['packages_evra']:
        name, version = row.split('\t')
        result.setdefault(name, []).append(version)
    return {name: sorted(versions) for name, versions in result.items()}


def arguments(value):
    tokens = value.split()
    assert tokens[0] == '<S>' and tokens[-1] == '<E>'
    tokens = tokens[1:-1]
    assert len(tokens) == len({x.split('=', 1)[0] for x in tokens})
    return sorted(tokens)


def compare(base, candidate):
    before, after = packages(base), packages(candidate)
    expected = {name: ['0:7.1.2-0.pocketfed.sdm670.12.fc46.aarch64'] for name in KERNEL}
    expected.update({'gnome-control-center': ['0:51~rc.1-1.2.fingerprint.fc46.aarch64'],
                    'gnome-control-center-filesystem': ['0:51~rc.1-1.2.fingerprint.fc46.noarch']})
    assert all(after.get(n) == v for n, v in expected.items()), 'Required package mismatch'
    assert {n: v for n, v in before.items() if n not in expected} == {
        n: v for n, v in after.items() if n not in expected}, 'Unrelated packages changed'
    assert base['kernel_release'] == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    assert candidate['kernel_release'] == '7.1.2-0.pocketfed.sdm670.12.fc46.aarch64'
    for field in ('outer_shim_sha256', 'dtb_sha256'):
        assert candidate['boot'][field] == base['boot'][field], field
    assert candidate['boot']['payloads_match_module_directory']
    assert arguments(base['boot']['cmdline']) == arguments(candidate['boot']['cmdline'])
    assert candidate['fingerprint_dt'] == base['fingerprint_dt']
    assert candidate['fingerprint_dt']['present']
    assert set(candidate['fingerprint_modules']) == {'fpc1020', 'qseecomtee'}
    assert all(v.split()[0] == candidate['kernel_release'] for v in candidate['fingerprint_modules'].values())
    assert candidate['initramfs_module_release_verified']
    assert candidate['initramfs_modules'] == base['initramfs_modules'], 'Initramfs module set changed'
    for group in ('authentication', 'systemd', 'selinux', 'activation_masks'):
        assert candidate[group] == base[group], group
    assert set(candidate['activation_masks'].values()) == {'/dev/null'}
    assert not candidate['broker_runtime_state_present'] and not candidate['initialization_marker_present']
    changed = {name for name in set(base['files']) | set(candidate['files'])
               if base['files'].get(name) != candidate['files'].get(name)}
    assert changed == {'/usr/libexec/pocketfed-verify-kernel'}, changed
    assert candidate['upgrade_report'] == base['upgrade_report'], 'Existing provenance changed'
    return {'expected_package_changes': expected, 'package_count': len(candidate['packages_evra']),
            'protected_groups_unchanged': ['authentication', 'systemd', 'selinux'],
            'boot_shim_dtb_arguments_preserved': True, 'initramfs_module_set_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--candidate-image', required=True)
    args = parser.parse_args()
    names = ('base-facts.json', 'candidate-facts.json')
    inputs = [args.evidence / name for name in names]
    report = compare(*(json.loads(p.read_text()) for p in inputs))
    report.update(status='Independent image comparison passed; not staged or booted',
                  candidate_image=args.candidate_image,
                  evidence_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    (args.evidence / 'image-comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
