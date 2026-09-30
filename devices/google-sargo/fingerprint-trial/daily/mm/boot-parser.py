#!/usr/bin/python3
"""Read package/configuration identity and independently validate Sargo boot payloads."""
import ctypes
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def u64(data, offset):
    return struct.unpack_from('<Q', data, offset)[0]


def canonical_kernel(data, expected_size):
    if data[4:8] == b'zimg':
        offset, size = u32(data, 8), u32(data, 12)
        assert offset + size <= len(data)
        data = data[offset:offset + size]
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    elif data[:4] == b'\x28\xb5\x2f\xfd':
        zstd = ctypes.CDLL('libzstd.so.1')
        zstd.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        zstd.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        size = zstd.ZSTD_getFrameContentSize(data, len(data))
        if size == 0xFFFFFFFFFFFFFFFF:
            size = expected_size
        assert 0 < size < 256 * 1024 * 1024
        output = ctypes.create_string_buffer(size)
        zstd.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_size_t]
        zstd.ZSTD_decompress.restype = ctypes.c_size_t
        assert zstd.ZSTD_decompress(output, size, data, len(data)) == size
        data = output.raw
    assert data[56:60] == b'ARM\x64'
    return data


def boot_facts(module):
    image = (module / 'aboot.img').read_bytes()
    assert image[:8] == b'ANDROID!' and u32(image, 40) == 2
    assert u32(image, 1644) == 1660
    page = u32(image, 36)
    assert page == 4096
    sizes = [u32(image, 8), u32(image, 16), u32(image, 24),
             u32(image, 1632), u32(image, 1648)]
    offset = page
    sections = []
    for size in sizes:
        assert offset + size <= len(image)
        sections.append(image[offset:offset + size])
        offset = (offset + size + page - 1) & -page
    assert offset == len(image) and len(image) < 64 * 1024 * 1024
    checksum = hashlib.sha1()
    for section in sections:
        checksum.update(section)
        checksum.update(struct.pack('<I', len(section)))
    assert image[576:608] == checksum.digest().ljust(32, b'\0')
    shim, ramdisk, second, recovery, dtb = sections
    assert dtb == (module / 'dtb/qcom/sdm670-google-sargo.dtb').read_bytes()
    assert ramdisk[:8] == b'ABLXRD1\0'
    assert u32(ramdisk, 8) == 72 and u32(ramdisk, 12) == 2
    kernel_offset, compressed_size, uncompressed_size = [u64(ramdisk, n) for n in (16, 24, 32)]
    initrd_offset, initrd_size = u64(ramdisk, 48), u64(ramdisk, 56)
    assert kernel_offset + compressed_size <= initrd_offset
    assert initrd_offset + initrd_size <= len(ramdisk)
    assert 0 < uncompressed_size < 256 * 1024 * 1024
    lz4 = ctypes.CDLL('liblz4.so.1')
    lz4.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lz4.LZ4_decompress_safe.restype = ctypes.c_int
    raw = ctypes.create_string_buffer(uncompressed_size)
    compressed = ramdisk[kernel_offset:kernel_offset + compressed_size]
    assert lz4.LZ4_decompress_safe(compressed, raw, compressed_size, uncompressed_size) == uncompressed_size
    assert raw.raw == canonical_kernel((module / 'vmlinuz').read_bytes(), uncompressed_size)
    initrd = ramdisk[initrd_offset:initrd_offset + initrd_size]
    assert initrd == (module / 'initramfs.img').read_bytes()
    assert module.name.encode() in raw.raw
    cmdline = (image[64:576].split(b'\0', 1)[0] + image[608:1632].split(b'\0', 1)[0]).decode()
    return {'bytes': len(image), 'sha256': sha(image), 'outer_shim_sha256': sha(shim),
            'dtb_sha256': sha(dtb), 'canonical_kernel_sha256': sha(raw.raw),
            'initramfs_sha256': sha(initrd), 'cmdline': cmdline,
            'payloads_match_module_directory': True}


packages = subprocess.check_output(['rpm', '-qa', '--qf',
    '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n'], text=True).splitlines()
files = {}
patterns = ['/usr/lib/pocketfed/*', '/usr/libexec/pocketfed-*',
            '/usr/lib/systemd/system/pocketfed-*', '/etc/dracut.conf.d/*',
            '/usr/lib/ostree-boot/*', '/usr/share/lpac/certs/*']
paths = {path for pattern in patterns for path in Path('/').glob(pattern.lstrip('/'))}
paths.update(Path(path) for path in ['/usr/bin/aboot-deploy', '/usr/libexec/abl-exorcist-assembler'])
for path in sorted(paths):
    if path.is_file():
        files[str(path)] = {'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}
modules = list(Path('/usr/lib/modules').iterdir())
assert len(modules) == 1 and modules[0].is_dir()
module = modules[0]
initrd_listing = subprocess.check_output(['lsinitrd', str(module / 'initramfs.img')], text=True)
module_lines = [line for line in initrd_listing.splitlines() if 'usr/lib/modules/' in line]
assert module_lines and all(module.name in line for line in module_lines)
print(json.dumps({'packages': sorted(packages), 'files': files,
                  'kernel_release': module.name, 'boot': boot_facts(module),
                  'initramfs_module_release_verified': True}, indent=2, sort_keys=True))
