#!/usr/bin/python3
"""Compile initialize-04.c with the same ARM64 compiler image and flags as before.

The helper sources are the exact hash-recorded files from the first probe
build; only initialize.c changes (new run identifiers). No network, no device.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
WORK = REPO / 'out/fingerprint-kernel-pool-20260913'
IMAGE = 'sha256:69ffaa7c0dec7f64cdd3cbfb877f69d3d7b7d840a5afc961e66ecba4bbcc9135'
FLAGS = ['-std=c11', '-O2', '-g', '-Wall', '-Wextra', '-Werror']
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
previous = json.loads((WORK / 'probe-preparation.json').read_text())['source']
source = WORK / 'native-source-04'
build = WORK / 'native-build-04'
source.mkdir()
build.mkdir()
for name, digest in previous.items():
    if name == 'initialize.c':
        continue
    origin = WORK / 'native-source' / name
    assert sha(origin) == digest, name
    shutil.copy2(origin, source / name)
shutil.copy2(HERE / 'initialize-04.c', source / 'initialize.c')
inspected = json.loads(subprocess.check_output(['podman', 'image', 'inspect', IMAGE], text=True))[0]
assert inspected['Id'] == IMAGE.removeprefix('sha256:') and inspected['Architecture'] == 'arm64'
command = ['podman', 'run', '--rm', '--pull=never', '--network=none', '--platform=linux/arm64',
           '--security-opt', 'label=disable', '--volume', f'{WORK}:/work:rw', IMAGE,
           'gcc', *FLAGS, '-I/work/native-source-04',
           '/work/native-source-04/initialize.c', '/work/native-source-04/protocol.c',
           '/work/native-source-04/qsee-transport.c', '/work/native-source-04/sensor.c',
           '-o', '/work/native-build-04/initialize']
with (build / 'build.log').open('x') as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
record = {'command': command, 'returncode': result.returncode, 'compiler_image': IMAGE,
          'compile_flags': FLAGS, 'network': False, 'hardware_accessed': False,
          'source': {p.name: sha(p) for p in sorted(source.iterdir())}}
if result.returncode == 0:
    record['probe_sha256'] = sha(build / 'initialize')
    record['file'] = subprocess.check_output(['file', '-b', str(build / 'initialize')], text=True).strip()
(build / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k: record[k] for k in record if k != 'command'}, indent=2))
result.check_returncode()
