#!/usr/bin/python3
"""Seal a module-only candidate against the exact packaged .11 kernel bundle."""
import hashlib
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess

REPO = Path(__file__).resolve().parents[5]
BASE = REPO / 'out/liveboot/fixtures/sargo-fingerprint11-local/kernel-bundle'
WORK = REPO / 'out/fingerprint-kernel-pool-20260913'
DEST = REPO / 'out/liveboot/candidates/sargo-fpc-pool-20260913'
TREE = Path('/var/home/sam/src/pocketfed-kernel-fpc-pool')
MODULE = WORK / 'kbuild/qseecom/qseecomtee.ko'
RELEASE = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(*args):
    return subprocess.check_output(args, text=True).strip()


base = json.loads((BASE / 'bundle.json').read_text())
assert base['release'] == RELEASE
assert capture('git', '-C', str(TREE), 'rev-parse', 'HEAD') == '132283913205a1db1d57fc3e563eea8224f5b79a'
assert capture('modinfo', '-F', 'vermagic', str(MODULE)) == RELEASE + ' SMP preempt mod_unload aarch64'
assert MODULE.read_bytes()[:6] == b'\x7fELF\x02\x01'
assert MODULE.read_bytes()[18:20] == b'\xb7\x00'
exports = {line.split()[1] for line in (WORK / 'kbuild/Module.symvers').read_text().splitlines()}
imports = {line.split()[-1] for line in capture('aarch64-linux-gnu-nm', '-u', str(MODULE)).splitlines()}
assert imports <= exports, imports - exports
for row in (base['image'], base['dtb']):
    assert sha(BASE / row['path']) == row['sha256']
for path, digest in base['module_files'].items():
    assert sha(BASE / base['modules_install'] / path) == digest, path

def config(path):
    return dict(re.findall(r'^(CONFIG_\w+)=(.*)$', path.read_text(), re.M))

old_config = config(BASE / 'kernel.config')
build_config = config(WORK / 'kbuild/.config')
deltas = {key: [old_config.get(key), build_config.get(key)]
          for key in old_config.keys() | build_config.keys()
          if old_config.get(key) != build_config.get(key)}
assert old_config['CONFIG_CC_VERSION_TEXT'] == build_config['CONFIG_CC_VERSION_TEXT']
# Missing Rust build tools changed only unrelated options. Prove none appears
# in the C translation units' source/header dependencies, including module glue.
checked = set()
for command in (WORK / 'kbuild/qseecom').glob('.*.o.cmd'):
    for name in re.findall(r'/source/[^\s\\]+', command.read_text()):
        source = TREE / name.removeprefix('/source/')
        if source.is_file() and source.suffix in ('.c', '.h'):
            content = source.read_text(errors='replace')
            assert not any(re.search(r'\b' + key + r'\b', content) for key in deltas), source
            checked.add(str(source.relative_to(TREE)))
assert len(checked) > 100

assert not DEST.exists()
DEST.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['cp', '-a', '--reflink=auto', str(BASE), str(DEST)], check=True)
targets = [name for name in base['module_files'] if name.endswith('/qseecomtee.ko.xz')]
assert len(targets) == 1
target = DEST / base['modules_install'] / targets[0]
target.write_bytes(lzma.compress(MODULE.read_bytes(), check=lzma.CHECK_CRC32))
subprocess.run(['depmod', '-b', str(DEST / base['modules_install']), RELEASE], check=True)
inventory = {str(path.relative_to(DEST / base['modules_install'])): sha(path)
             for path in (DEST / base['modules_install']).rglob('*') if path.is_file()}
changes = {name: {'before': base['module_files'].get(name), 'after': digest}
           for name, digest in inventory.items() if base['module_files'].get(name) != digest}
assert not (base['module_files'].keys() - inventory.keys())
assert all(name == targets[0] or Path(name).name.startswith('modules.') for name in changes)
base['module_files'] = inventory
(DEST / 'bundle.json').write_text(json.dumps(base, indent=2, sort_keys=True) + '\n')
provenance = {
    'base_bundle_sha256': sha(BASE / 'bundle.json'), 'source_commit': capture('git', '-C', str(TREE), 'rev-parse', 'HEAD'),
    'source_patch_sha256': sha(Path(__file__).with_name('0001-qseecom-trial-reuse-invoke-pool.patch')),
    'compiler_image': 'sha256:69ffaa7c0dec7f64cdd3cbfb877f69d3d7b7d840a5afc961e66ecba4bbcc9135',
    'compiler': old_config['CONFIG_CC_VERSION_TEXT'], 'module_sha256': sha(MODULE),
    'module_vermagic': capture('modinfo', '-F', 'vermagic', str(MODULE)),
    'module_imports_verified': len(imports), 'checked_source_dependencies': sorted(checked),
    'module_build_config_deltas': deltas, 'changed_bundle_files': changes,
    'kernel_and_dtb_unchanged': True, 'local_unsigned_module': True,
    'installed_deployment_modified': False, 'hardware_result': 'not yet booted',
}
(DEST / 'module-provenance.json').write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: provenance[key] for key in ('module_sha256', 'module_vermagic', 'module_imports_verified', 'changed_bundle_files')}, indent=2))
