#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Replace only a Sargo Android-v2 template DTB during an offline image build.

Never writes a block device or overwrites an existing output. The inherited
PocketFed finalizer subsequently replaces the ABLX kernel/initramfs payload.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess

LIMIT = 64 * 1024 * 1024
SIZE_FIELDS = (8, 16, 24, 1632, 1648)


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def padded(data, page):
    return data + bytes((-len(data)) % page)


def parse(data):
    if len(data) < 4096 or len(data) > LIMIT or data[:8] != b'ANDROID!':
        raise ValueError('not a bounded Android boot image')
    page = u32(data, 36)
    if page != 4096 or u32(data, 40) != 2 or u32(data, 1644) != 1660:
        raise ValueError('expected Android v2 with a 4096-byte header page')
    offset, sections = page, []
    for field in SIZE_FIELDS:
        size = u32(data, field)
        if offset + size > len(data):
            raise ValueError('truncated boot payload')
        if field == 1632 and size and struct.unpack_from('<Q', data, 1636)[0] != offset:
            raise ValueError('recovery DTBO offset does not match its payload')
        sections.append(data[offset:offset + size])
        offset = (offset + size + page - 1) & -page
    if offset != len(data) or not all(sections[i] for i in (0, 1, 4)):
        raise ValueError('trailing data or missing kernel/ramdisk/DTB')
    if data[576:608] != checksum(sections):
        raise ValueError('Android payload SHA-1 does not match')
    return bytearray(data[:page]), sections


def checksum(sections):
    digest = hashlib.sha1()
    for section in sections:
        digest.update(section)
        digest.update(struct.pack('<I', len(section)))
    return digest.digest().ljust(32, b'\0')


def replace(data, dtb):
    header, sections = parse(data)
    if len(dtb) < 40 or dtb[:4] != b'\xd0\x0d\xfe\xed':
        raise ValueError('replacement is not a flattened device tree')
    if struct.unpack_from('>I', dtb, 4)[0] != len(dtb):
        raise ValueError('DTB total size does not match the file')
    sections[-1] = dtb
    struct.pack_into('<I', header, 1648, len(dtb))
    header[576:608] = checksum(sections)
    result = bytes(header) + b''.join(padded(section, 4096) for section in sections)
    if len(result) > LIMIT:
        raise ValueError('result exceeds the Sargo 64 MiB boot partition')
    check_header, check_sections = parse(result)
    if check_sections[:-1] != parse(data)[1][:-1] or check_sections[-1] != dtb:
        raise ValueError('payload preservation verification failed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template', type=Path)
    parser.add_argument('dtb', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must not already exist')
    dtb_path = args.dtb.resolve()
    expected = [('/', 'compatible', 'google,sargo'),
                ('/fingerprint', 'compatible', 'google,sargo-fingerprint'),
                ('/fingerprint', 'firmware-name', 'fpctzappfingerprint')]
    for node, prop, value in expected:
        actual = subprocess.check_output(['fdtget', '-t', 's', str(dtb_path), node, prop],
                                         text=True).split()
        if value not in actual:
            parser.error(f'DTB {node}/{prop} does not identify {value}')
    result = replace(args.template.read_bytes(), dtb_path.read_bytes())
    with args.output.open('xb') as output:
        output.write(result)
    print(f'PASS: new Sargo fingerprint DTB, inherited payloads preserved, {len(result)} bytes')


if __name__ == '__main__':
    main()
