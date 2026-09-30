#!/usr/bin/python3
"""Offline ARM64 build of a hash-checked diagnostic libfprint source copy.

Uses the existing fingerprint toolchain. Does not install, publish or access
hardware. Run only when normal container/tool approval is available.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--image', required=True, help='Full sha256 image ID of an existing ARM64 toolchain')
    args = p.parse_args()
    image = args.image
    assert image.startswith('sha256:') and len(image) == 71
    assert all(c in '0123456789abcdef' for c in image[7:])
    root = args.prepared.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    source_name = 'libfprint-' + manifest['source_commit']
    assert source_name == 'libfprint-430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a'
    driver = root / source_name / 'libfprint/drivers/fpcqsee'
    for name, sha in manifest['changed_sources'].items():
        assert hashlib.sha256((driver / name).read_bytes()).hexdigest() == sha
    assert not (root / 'build-arm64').exists()
    inspected = json.loads(subprocess.check_output(['podman', 'image', 'inspect', image], text=True))[0]
    assert inspected['Id'].removeprefix('sha256:') == image.removeprefix('sha256:')
    assert inspected['Architecture'] == 'arm64'
    command = [
        'podman', 'run', '--rm', '--pull=never', '--network=none',
        '--platform=linux/arm64', '--security-opt', 'label=disable',
        '--volume', f'{root}:/work:rw', image, 'sh', '-ec',
        'meson setup /work/build-arm64 /work/' + source_name +
        ' --prefix=/usr --libdir=lib64 --wrap-mode=nodownload'
        ' -Ddrivers=all -Ddoc=false -Dintrospection=false'
        ' -Dinstalled-tests=false -Dudev_hwdb=disabled\n'
        'meson compile -C /work/build-arm64 -j 8\n'
        'meson test -C /work/build-arm64 --suite unit-tests --suite fpcqsee --print-errorlogs\n',
    ]
    (root / 'arm64-build-command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (root / 'arm64-build.log').open('x') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    (root / 'arm64-build-result.json').write_text(json.dumps({
        'returncode': result.returncode, 'image': image,
        'trace_patch_sha256': manifest['trace_patch_sha256'],
        'hardware_accessed': False, 'installed': False,
    }, indent=2) + '\n')
    result.check_returncode()
    print('ARM64 build and unit/FPC tests passed; hardware acceptance remains pending.')


if __name__ == '__main__':
    main()
