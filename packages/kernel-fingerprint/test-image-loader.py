#!/usr/bin/env python3
"""Compile production QSEECOM ELF assembly with mocked firmware I/O.

No firmware bytes are written into this repository. Optional stock firmware
paths are read to exercise the same production functions against real data.
"""
import argparse
import ctypes
import pathlib
import struct
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('kernel', type=pathlib.Path)
parser.add_argument('--mdt', type=pathlib.Path)
parser.add_argument('--mbn', type=pathlib.Path)
args = parser.parse_args()
source = (args.kernel / 'drivers/soc/qcom/mdt_loader.c').read_text()
start = source.index('struct qcom_mdt_image {')
end = source.index('/**\n * qcom_mdt_read_metadata()', start)
body = source[start:end]
for before, after in [('struct elf32_hdr', 'Elf32_Ehdr'),
                      ('struct elf64_hdr', 'Elf64_Ehdr'),
                      ('struct elf32_phdr', 'Elf32_Phdr'),
                      ('struct elf64_phdr', 'Elf64_Phdr')]:
    body = body.replace(before, after)
fixture = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <limits.h>
#include <elf.h>
#include <sys/types.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint64_t u64;
#define GFP_KERNEL 0
#define EXPORT_SYMBOL_GPL(x)
#define check_add_overflow(a,b,p) __builtin_add_overflow(a,b,p)
#define kfree free
struct firmware { size_t size; const u8 *data; };
struct device { int unused; };
static u16 get_unaligned_le16(const void *p) { u16 x; memcpy(&x,p,2); return x; }
static uint32_t get_unaligned_le32(const void *p) { uint32_t x; memcpy(&x,p,4); return x; }
static u64 get_unaligned_le64(const void *p) { u64 x; memcpy(&x,p,8); return x; }
static char *kasprintf(int flags, const char *format, ...) {
    char *s = NULL; va_list ap; va_start(ap,format);
    int n = vasprintf(&s,format,ap); va_end(ap); return n < 0 ? NULL : s;
}
static const u8 *segments[64];
static size_t sizes[64];
static int requests;
static int request_firmware_into_buf(const struct firmware **result,
                                     const char *name, struct device *dev,
                                     void *dst, size_t capacity) {
    const char *suffix = strrchr(name,'.');
    unsigned i; requests++;
    if (!suffix || sscanf(suffix,".b%u",&i) != 1 || i >= 64 || !segments[i])
        return -ENOENT;
    if (sizes[i] > capacity) return -EFBIG;
    struct firmware *fw = malloc(sizeof(*fw));
    if (!fw) return -ENOMEM;
    fw->data=segments[i]; fw->size=sizes[i];
    memcpy(dst,fw->data,fw->size); *result=fw; return 0;
}
static void release_firmware(const struct firmware *fw) { free((void*)fw); }
'''
wrappers = r'''
ssize_t image_size(const void *data, size_t size) {
    struct firmware fw={size,data}; return qcom_mdt_get_image_size(&fw);
}
ssize_t assemble(const void *data, size_t size, void *out, size_t capacity) {
    struct firmware fw={size,data}; struct device dev={0};
    return qcom_mdt_read_image(&dev,&fw,"test.mdt",out,capacity);
}
void set_segment(unsigned i, const void *p, size_t n) { segments[i]=p; sizes[i]=n; }
'''

def synthetic(bits):
    if bits == 64:
        hdr = bytearray(64 + 2 * 56)
        hdr[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
        struct.pack_into('<Q', hdr, 32, 64)
        struct.pack_into('<HH', hdr, 54, 56, 2)
        struct.pack_into('<IIQQQQQQ', hdr, 64, 0, 0, 0, 0, 0, 16, 16, 8)
        struct.pack_into('<IIQQQQQQ', hdr, 120, 1, 5, 4096, 0, 0, 24, 24, 8)
    else:
        hdr = bytearray(52 + 2 * 32)
        hdr[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
        struct.pack_into('<I', hdr, 28, 52)
        struct.pack_into('<HH', hdr, 42, 32, 2)
        struct.pack_into('<IIIIIIII', hdr, 52, 0, 0, 0, 0, 16, 16, 0, 8)
        struct.pack_into('<IIIIIIII', hdr, 84, 1, 4096, 0, 0, 24, 24, 5, 8)
    return bytes(hdr)

with tempfile.TemporaryDirectory(prefix='sargo-qsee-image-test-') as tmp:
    tmp = pathlib.Path(tmp)
    c = tmp / 'test.c'
    c.write_text(fixture + body + wrappers)
    so = tmp / 'test.so'
    subprocess.run(['/usr/bin/cc', '-shared', '-fPIC', '-O1', '-g',
                    '-fsanitize=undefined', '-fsanitize-undefined-trap-on-error',
                    '-Wall', '-Wextra', '-Wno-unused-parameter',
                    '-o', str(so), str(c)], check=True)
    lib = ctypes.CDLL(str(so))
    lib.image_size.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.image_size.restype = ctypes.c_ssize_t
    lib.assemble.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                            ctypes.c_void_p, ctypes.c_size_t]
    lib.assemble.restype = ctypes.c_ssize_t
    lib.set_segment.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t]
    keep = []

    def set_segments(parts):
        keep.clear()
        for i, part in enumerate(parts):
            b = ctypes.create_string_buffer(part)
            keep.append(b)
            lib.set_segment(i, b, len(part))

    def check_assembly(header, parts):
        set_segments(parts)
        expected = header + b''.join(parts)
        actual = lib.image_size(header, len(header))
        assert actual == len(expected), (actual, len(expected))
        out = ctypes.create_string_buffer(len(expected))
        assert lib.assemble(header, len(header), out, len(out)) == len(expected)
        assert out.raw == expected
        assert lib.assemble(header, len(header), out, len(out)-1) == -28

    for bits in (32, 64):
        header = synthetic(bits)
        check_assembly(header, [b'a'*16, b'b'*24])
        set_segments([b'a'*16, b'b'*23])
        out = ctypes.create_string_buffer(len(header)+40)
        assert lib.assemble(header, len(header), out, len(out)) == -22
        for n in (0, 15, 40, len(header)-1):
            assert lib.image_size(header, n) < 0
        bad = bytearray(header); bad[5] = 2
        assert lib.image_size(bytes(bad),len(bad)) == -22
        bad = bytearray(header); bad[4] = 0
        assert lib.image_size(bytes(bad),len(bad)) == -22
        bad = bytearray(header); bad[0] = 0
        assert lib.image_size(bytes(bad),len(bad)) == -22
        bad = bytearray(header)
        struct.pack_into('<H',bad,56 if bits == 64 else 44,0)
        assert lib.image_size(bytes(bad),len(bad)) == -22
    bad = bytearray(synthetic(64))
    struct.pack_into('<Q',bad,32,(1<<64)-1)
    assert lib.image_size(bytes(bad),len(bad)) == -22
    bad = bytearray(synthetic(64))
    struct.pack_into('<Q',bad,120+32,(1<<64)-1)
    assert lib.image_size(bytes(bad),len(bad)) == -22
    print('PASS: production ELF32/ELF64 assembly, exact payloads, truncated segments,')
    print('      destination bounds, truncated headers, invalid class/data/header, overflow')

    if args.mdt and args.mbn:
        header = args.mdt.read_bytes(); mbn = args.mbn.read_bytes()
        assert header[4] == 2
        phoff = struct.unpack_from('<Q',header,32)[0]
        phnum = struct.unpack_from('<H',header,56)[0]
        parts=[]
        for i in range(phnum):
            off = phoff+i*56
            offset = struct.unpack_from('<Q',header,off+8)[0]
            size = struct.unpack_from('<Q',header,off+32)[0]
            assert offset+size <= len(mbn)
            parts.append(mbn[offset:offset+size])
        check_assembly(header, parts)
        print(f'PASS: exact stock Sargo ELF64 MDT, {phnum} segments, '
              f'{len(header)+sum(map(len,parts))} assembled bytes')
