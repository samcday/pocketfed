#!/usr/bin/python3
"""Offline build of a daily-only CPU comparison; no device access."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ROOT = REPO / 'out/fingerprint-daily-cpu-compare-20260913-v2'
TOOLCHAIN = 'sha256:69ffaa7c0dec7f64cdd3cbfb877f69d3d7b7d840a5afc961e66ecba4bbcc9135'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
ROOT.mkdir(mode=0o700)
source = ROOT / 'source'
source.mkdir()
reference = json.loads((HERE.parent / 'driver-trace/source-manifest.json').read_text())
old = REPO / 'out/fingerprint-kernel-trace-20260913/source'
for name in ('protocol.c', 'qsee-transport.c', 'sensor.c', 'trial-trace.h'):
    assert sha(old / name) == reference['changed_sources'][name]
for name in ('protocol.c', 'protocol.h', 'qsee-transport.c', 'qsee-transport.h',
             'sensor.c', 'sensor.h', 'fpc1020.h', 'trial-trace.h'):
    shutil.copy2(old / name, source / name)
shutil.copy2(HERE / 'initialize-once.c', source)
bundle = ROOT / 'bundle'
bundle.mkdir(mode=0o700)
command = ['podman', 'run', '--rm', '--pull=never', '--network=none', '--cap-drop=all',
           '--security-opt=label=disable', '-v', str(source) + ':/source:ro',
           '-v', str(bundle) + ':/build:rw', TOOLCHAIN, 'gcc', '-std=c11',
           '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-I/source',
           '/source/initialize-once.c', '/source/protocol.c',
           '/source/qsee-transport.c', '/source/sensor.c', '-o', '/build/initialize-once']
(ROOT / 'build-command.json').write_text(json.dumps(command, indent=2) + '\n')
with (ROOT / 'build.log').open('w') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
binary = bundle / 'initialize-once'
assert binary.read_bytes()[:6] == b'\x7fELF\x02\x01' and binary.read_bytes()[18:20] == b'\xb7\x00'
for name in ('controller.py', 'install.py'):
    shutil.copy2(HERE / name, bundle)
shutil.copy2(HERE.parent.parent / 'lab/kernel-trace/trace-init.py', bundle / 'trace-core.py')
for path in bundle.glob('*.py'):
    ast.parse(path.read_text())
subprocess.run(['python3', str(HERE.parent.parent / 'lab/kernel-trace/test-trace.py')], check=True)
manifest = {'serial': '994AY18RSD', 'boot_id': '0ac24861-f5de-4f09-8128-fd24c2f80070',
            'toolchain': TOOLCHAIN, 'probe_sha256': sha(binary),
            'protocol_source_commit': reference['source_commit'],
            'source': {p.name: sha(p) for p in source.iterdir()},
            'bundle': {p.name: sha(p) for p in bundle.iterdir()},
            'operations': ['sensor open', 'TEE session', 'reset', 'INIT', 'DEEP_SLEEP', 'close'],
            'cpu_order': [7, 1], 'automatic_retry': False,
            'credential_operations': False, 'capture_started': False}
(bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
