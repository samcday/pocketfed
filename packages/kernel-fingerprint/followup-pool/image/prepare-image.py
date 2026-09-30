#!/usr/bin/python3
"""Assemble the exact local context after COPR artifact verification; no device access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parent
OUT = ROOT / 'out/fingerprint-pool-fix-20260913'
BASE = 'sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861'
DT_TOOLS = 'sha256:f364b6e2612480f28b648647f99e302aa7c2b21234ce483918e4b77335508543'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    evidence = json.loads((OUT / 'kernel-rpms.json').read_text())
    assert evidence['build_id'] == 10980882 and evidence['state'] == 'succeeded'
    assert len(evidence['rpms']) == 4
    context = OUT / 'image-context'
    context.mkdir()
    kernel = context / 'inputs/kernel-rpms'
    settings = context / 'inputs/settings-rpms'
    kernel.mkdir(parents=True)
    settings.mkdir()
    artifacts = []
    for record in evidence['rpms']:
        path = Path(record['path'])
        assert sha(path) == record['sha256']
        assert record['signature_fingerprint'] == 'e58892d1cbf2fac58a3490c94e2c57a4a2603023'
        shutil.copyfile(path, kernel / path.name)
        artifacts.append(record)
    (kernel / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(kernel.glob('*.rpm'))))
    settings_root = ROOT / 'out/fingerprint-daily-mm-20260912/gcc-rpmbuild-second-enroll/RPMS'
    for name, arch, digest in (
        ('gnome-control-center', 'aarch64', '707e028a23c0a9a6a38dc41f397b1a07862650e50546d20093714dcb4cbbf063'),
        ('gnome-control-center-filesystem', 'noarch', 'bb0592aebdf41df71d281d9004a3a5f400343fbd04fbcbe912ef1e7427d97602')):
        path = settings_root / arch / f'{name}-51~rc.1-1.2.fingerprint.fc46.{arch}.rpm'
        assert sha(path) == digest
        shutil.copyfile(path, settings / path.name)
        artifacts.append({'path': str(path), 'sha256': digest, 'source': 'Existing local Settings build'})
    for name in ('Containerfile', 'install-kernel.sh', 'install-candidate.py'):
        shutil.copyfile(SOURCE / name, context / name)
    shutil.copyfile(ROOT / 'packages/kernel-fingerprint/replace-template-dtb.py', context / 'replace-template-dtb.py')
    spec = importlib.util.spec_from_file_location('comparison', SOURCE / 'compare-images.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = json.loads((OUT / 'base-facts.json').read_text())
    manifest = {'base_image': BASE, 'dt_tools_image': DT_TOOLS,
                'files': {str(p.relative_to(context / 'inputs')): sha(p)
                          for p in sorted((context / 'inputs').rglob('*')) if p.is_file()},
                'base_packages': module.packages(base),
                'protected_files': json.loads((OUT / 'base-protected.json').read_text()),
                'package_artifacts': artifacts}
    (context / 'inputs/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    command = ['podman', 'build', '--pull=never', '--network=none', '--platform=linux/arm64',
               '--security-opt', 'label=disable', '--build-arg', 'BASE_IMAGE=' + BASE,
               '--build-arg', 'DT_TOOLS_IMAGE=' + DT_TOOLS, '--iidfile', str(OUT / 'candidate-image.id'),
               '-t', 'localhost/sargo-fingerprint-pool:20260913', '-f', str(context / 'Containerfile'), str(context)]
    (OUT / 'image-build-command.json').write_text(json.dumps(command, indent=2) + '\n')
    print(json.dumps({'context': str(context), 'files': len(manifest['files']),
                      'package_artifacts': len(artifacts), 'build_command': command}, indent=2))


if __name__ == '__main__':
    main()
