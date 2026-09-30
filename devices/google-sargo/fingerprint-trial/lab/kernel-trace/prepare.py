#!/usr/bin/python3
"""Build the isolated ARM64 init probe and prepare its disposable overlay."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
REPO = LAB.parents[3]
RUN = 'sargo-fingerprint-lab-kernel-trace-20260913'
ROOT = REPO / 'out/fingerprint-kernel-trace-20260913'
IMAGE = 'sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861'
TOOLCHAIN = 'sha256:69ffaa7c0dec7f64cdd3cbfb877f69d3d7b7d840a5afc961e66ecba4bbcc9135'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
ROOT.mkdir(mode=0o700)
source = REPO / 'out/fingerprint-driver-trace-20260912-v2/libfprint-430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a/libfprint/drivers/fpcqsee'
reference = json.loads((LAB.parent / 'daily/driver-trace/source-manifest.json').read_text())
snapshot = ROOT / 'source'
snapshot.mkdir()
for name in ('protocol.c', 'qsee-transport.c', 'sensor.c', 'trial-trace.h'):
    assert sha(source / name) == reference['changed_sources'][name], name
for name in ('protocol.c', 'protocol.h', 'qsee-transport.c', 'qsee-transport.h',
             'sensor.c', 'sensor.h', 'fpc1020.h', 'trial-trace.h'):
    shutil.copy2(source / name, snapshot / name)
shutil.copy2(HERE / 'initialize-once.c', snapshot)
build = ROOT / 'build'
build.mkdir()
info = json.loads(subprocess.check_output(['podman', 'image', 'inspect', TOOLCHAIN], text=True))[0]
assert info['Id'].removeprefix('sha256:') == TOOLCHAIN.removeprefix('sha256:')
assert info['Architecture'] == 'arm64'
command = ['podman', 'run', '--rm', '--pull=never', '--network=none', '--cap-drop=all',
           '--security-opt=label=disable', '-v', str(snapshot) + ':/source:ro',
           '-v', str(build) + ':/build:rw', TOOLCHAIN, 'gcc', '-std=c11',
           '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-I/source',
           '/source/initialize-once.c', '/source/protocol.c',
           '/source/qsee-transport.c', '/source/sensor.c', '-o', '/build/initialize-once']
(ROOT / 'build-command.json').write_text(json.dumps(command, indent=2) + '\n')
with (ROOT / 'build.log').open('w') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
binary = build / 'initialize-once'
elf = binary.read_bytes()
assert elf[:6] == b'\x7fELF\x02\x01' and elf[18:20] == b'\xb7\x00'
subprocess.run(['python3', str(HERE / 'test-trace.py')], check=True)

overlay = ROOT / 'overlay'
base = REPO / 'out/liveboot/overlays/sargo-fingerprint-ordered-20260911'
shutil.copytree(base, overlay, symlinks=True)
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
for name in ('lab_report.py', 'guard-device.py', 'inspect-device.py', 'stage-firmware.py'):
    shutil.copy2(LAB / name, code / name)
shutil.copy2(HERE / 'trace-init.py', code / 'trial-startup.py')
shutil.copy2(binary, code / 'initialize-once')
(code / 'initialize-once').chmod(0o755)
units = overlay / 'usr/lib/systemd/system'
startup = units / 'pocketfed-fingerprint-lab-startup.service'
text = startup.read_text()
assert text.count('ConditionKernelCommandLine=pocketfed.liveboot\n') == 1
text = text.replace('ConditionKernelCommandLine=pocketfed.liveboot\n',
                    'ConditionKernelCommandLine=pocketfed.liveboot=' + RUN + '\n'
                    'ConditionKernelCommandLine=androidboot.serialno=99NAY1AZG1\n'
                    'ConditionKernelCommandLine=pocketfed.root_mode=usb\n')
startup.write_text(text)
# The controller calls only the new guarded init executable. Keep old probe
# unit inaccessible to accidental activation in this disposable root.
etc_units = overlay / 'etc/systemd/system'
(etc_units / 'pocketfed-fingerprint-lab-probe.service').symlink_to('/dev/null')
for unit in ('fprintd.service', 'pocketfed-fpc-auth.service',
             'pocketfed-fpc-auth.socket', 'phosh-fingerprint-auth.socket',
             'phosh-fingerprint-auth@.service'):
    mask = etc_units / unit
    if mask.is_symlink():
        assert mask.readlink() == Path('/dev/null')
    else:
        assert not mask.exists()
        mask.symlink_to('/dev/null')
profile = json.loads((REPO / 'out/liveboot/profiles/sargo-fingerprint-ordered-20260911.json').read_text())
profile['fixture_image'] = IMAGE
(ROOT / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
result = {'run_id': RUN, 'serial': '99NAY1AZG1', 'fixture_image': IMAGE,
          'toolchain_image': TOOLCHAIN, 'probe_sha256': sha(binary),
          'protocol_source_commit': reference['source_commit'],
          'source': {p.name: sha(p) for p in snapshot.iterdir()},
          'overlay_base': str(base), 'controller_sha256': sha(code / 'trial-startup.py'),
          'receiver_sha256': sha(code / 'rpmb-supplicant-ro'),
          'keymaster_helper_sha256': sha(code / 'keymaster-startup'),
          'runtime': 'not booted', 'capture_started': False,
          'credential_or_template_input': False, 'kernel_modified': False}
(ROOT / 'preparation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
