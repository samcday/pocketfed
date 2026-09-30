#!/usr/bin/python3
"""Install only the exact policy outputs already validated outside the image."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat

TARGETS = {
    'policy.35': '/etc/selinux/targeted/policy/policy.35',
    'file_contexts': '/etc/selinux/targeted/contexts/files/file_contexts',
    'file_contexts.bin': '/etc/selinux/targeted/contexts/files/file_contexts.bin',
}


def facts(path):
    assert stat.S_ISREG(path.lstat().st_mode), path
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('inputs', type=Path)
    args = parser.parse_args()
    assert stat.S_ISDIR(args.inputs.lstat().st_mode)
    assert {p.name for p in args.inputs.iterdir()} == set(TARGETS) | {'manifest.json'}
    facts(args.inputs / 'manifest.json')
    manifest = json.loads((args.inputs / 'manifest.json').read_text())
    assert set(manifest['files']) == set(TARGETS)
    for name, target in TARGETS.items():
        record = manifest['files'][name]
        assert record['target'] == target
        assert facts(args.inputs / name) == record['candidate'], name
    if args.check_only:
        print('PASS: exact reviewed policy input set')
        return
    assert Path('/run/.containerenv').exists() or Path('/.dockerenv').exists()
    assert (args.inputs / 'manifest.json').read_bytes() == Path(
        '/usr/share/pocketfed/fingerprint-trial/policy-artifacts.json').read_bytes()
    module = Path('/usr/share/selinux/packages/targeted/pocketfed_fpc.pp')
    assert facts(module)['sha256'] == manifest['module_pp_sha256']
    # Validate every destination before changing any file. Keep existing modes
    # and ownership; compiled regex input was produced using the ARM64 base.
    for name, target in TARGETS.items():
        assert facts(Path(target)) == manifest['files'][name]['base'], target
    for name, target in TARGETS.items():
        shutil.copyfile(args.inputs / name, target)
        assert facts(Path(target)) == manifest['files'][name]['candidate']
    print('PASS: installed verified policy outputs; no policy load or relabeling')


if __name__ == '__main__':
    main()
