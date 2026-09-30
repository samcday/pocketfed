#!/usr/bin/python3
"""Prepare a header-only temporary boot of the verified daily deployment."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = ROOT / 'out/fingerprint-daily-recovery-20260912'
RELEASE = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
source = OUT / RELEASE
reference = json.loads((HERE / 'mm/boot-preview-validation.json').read_text())
parser = HERE / 'mm/boot-parser.py'
tree = ast.parse(parser.read_text())
tree.body = [node for node in tree.body
             if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
namespace = {}
exec(compile(tree, str(parser), 'exec'), namespace)
facts = namespace['boot_facts'](source)
payload_keys = ('outer_shim_sha256', 'dtb_sha256',
                'canonical_kernel_sha256', 'initramfs_sha256')
for key in payload_keys:
    assert facts[key] == reference['boot_preview'][key], key

masks = ['fprintd.service', 'phosh-fingerprint-auth.socket',
         'phosh-fingerprint-auth@.service']
options = reference['boot_preview']['cmdline'].split()
assert options.pop(0) == '<S>' and options.pop() == '<E>'
assert sum(x.startswith('ostree=') for x in options) == 1
options = [x for x in options if x != 'quiet']
options += ['console=ttyMSM0,115200n8']
options += ['systemd.mask=' + unit for unit in masks]
cmdline = ('<S> ' + ' '.join(options) + ' <E>').encode()
assert len(cmdline) <= 1534 and b'\0' not in cmdline
original = (source / 'aboot.img').read_bytes()
image = bytearray(original)
image[64:576] = cmdline[:511].ljust(512, b'\0')
image[608:1632] = cmdline[511:].ljust(1024, b'\0')
# Android v2 ID covers payloads and sizes, not the command-line fields.
assert image[:64] == original[:64]
assert image[576:608] == original[576:608]
assert image[1632:] == original[1632:]
destination = OUT / 'paused' / RELEASE
destination.mkdir(parents=True)
for name in ('vmlinuz', 'initramfs.img', 'dtb'):
    (destination / name).symlink_to(source / name)
(destination / 'aboot.img').write_bytes(image)
result = namespace['boot_facts'](destination)
assert result['cmdline'] == cmdline.decode()
for key in payload_keys:
    assert result[key] == facts[key], key
manifest = {
    'status': 'verified header-only recovery boot; not yet booted',
    'device_serial': '994AY18RSD', 'product': 'sargo',
    'source_image': json.loads((OUT / 'source.json').read_text())['image'],
    'deployment': reference['staged_checksum'],
    'source_boot': facts, 'recovery_boot': result,
    'image_path': str(destination / 'aboot.img'),
    'runtime_masks': masks, 'payload_bytes_unchanged': True,
    'partition_written': False,
    'options_basis': 'Installed preview also confirmed by captured previous-boot kernel command line',
    'next_step': 'fastboot boot exact serial after renamed daily UART capture is ready',
}
(OUT / 'paused-boot.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'status': manifest['status'], 'sha256': result['sha256'],
                  'bytes': result['bytes'], 'runtime_masks': masks}, indent=2))
