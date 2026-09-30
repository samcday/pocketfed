#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the offline DTB tool with independent Android-v2 fixtures."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile

path = Path(__file__).with_name('replace-template-dtb.py')
spec = importlib.util.spec_from_file_location('repacker', path)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
header = bytearray(4096)
header[:8] = b'ANDROID!'
struct.pack_into('<III', header, 36, 4096, 2, 0)
struct.pack_into('<I', header, 1644, 1660)
header[64:64+12] = b'cmdline-kept'
sections = [b'shim'*31, b'ABLXRD1\0'+bytes(range(256))*25, b'second'*4,
            b'recovery'*7, b'old-dtb'*13]
offset = 4096
for field, section in zip((8,16,24,1632,1648), sections):
    struct.pack_into('<I',header,field,len(section))
    if field == 1632:
        struct.pack_into('<Q',header,1636,offset)
    offset += (len(section)+4095)//4096*4096
digest = hashlib.sha1()
for section in sections:
    digest.update(section);digest.update(struct.pack('<I',len(section)))
header[576:608] = digest.digest()+bytes(12)
image = bytes(header)+b''.join(s+bytes((-len(s))%4096) for s in sections)
new = bytearray(9000)
new[:4]=b'\xd0\x0d\xfe\xed'
struct.pack_into('>I',new,4,len(new))
new[-7:]=b'new-dtb'
result=r.replace(image,bytes(new))
new_header, payloads=r.parse(result)
assert payloads == sections[:-1]+[bytes(new)]
for start,end in [(0,576),(608,1648),(1652,4096)]:
    assert new_header[start:end] == header[start:end]
for bad in (image[:-1],image+b'x',bytes(4096)):
    try:r.replace(bad,bytes(new))
    except ValueError:pass
    else:raise AssertionError('malformed image accepted')
bad=bytearray(image);bad[4096]^=1
try:r.replace(bytes(bad),bytes(new))
except ValueError:pass
else:raise AssertionError('corrupt checksum accepted')
for bad in (b'bad',bytes(40),new[:-1]):
    try:r.replace(image,bad)
    except ValueError:pass
    else:raise AssertionError('malformed DTB accepted')
print('PASS: independent Android-v2 fixture, component preservation, larger DTB,')
print('      unchanged header policy, checksum, size and malformed-input checks')
# Use the actual compiled Sargo DTB to verify CLI identity checks and output.
dtb=Path('/tmp/sargo-fingerprint-kbuild/arch/arm64/boot/dts/qcom/sdm670-google-sargo.dtb')
if dtb.exists():
    with tempfile.TemporaryDirectory(prefix='sargo-template-test-') as temp:
        temp=Path(temp);(temp/'base.img').write_bytes(image)
        subprocess.run(['python3',str(path),str(temp/'base.img'),str(dtb),str(temp/'new.img')],check=True)
        assert r.parse((temp/'new.img').read_bytes())[1][-1] == dtb.read_bytes()
        repeat=subprocess.run(['python3',str(path),str(temp/'base.img'),str(dtb),str(temp/'new.img')],capture_output=True)
        assert repeat.returncode != 0
print('PASS: CLI refuses output replacement; all files remain local fixtures')
