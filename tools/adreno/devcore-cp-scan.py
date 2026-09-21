#!/usr/bin/env python3
"""Scan an msm (a3xx) GPU devcoredump for CP_LOAD_STATE packets.

`/sys/class/devcoredump/devcd*/data` from drm/msm is YAML with the ringbuffer
and the submit's buffer objects appended as ascii85 payloads. Each payload is
a sequence of u32s encoded most-significant byte first, so a naive
little-endian read of the decoded bytes produces byte-swapped dwords and finds
nothing.

This walks every payload as a3xx type-3 packets and decodes every
CP_LOAD_STATE (opcode 0x30), which is what tells you whether a hung submit
contains the a306 fragment-stage indirect constant load:

    dst_off=16  SS_INDIRECT  SB_FRAG_SHADER  num_unit=32  ST_CONSTANTS

The same packet targeting SB_VERT_SHADER is benign on this hardware, so the
vertex/fragment split in the summary is the interesting part.

This does not tell you which draw was executing when the GPU wedged: the dump
carries ringbuffer read/write pointers, not an instruction pointer into an IB,
and GPU execution is asynchronous. It tells you what the submit contained.

usage: devcore-cp-scan.py <devcoredump> [--all]
       --all also lists packets that are not constant loads
"""

import base64
import re
import sys

SB = {0: 'SB_VERT_TEX', 1: 'SB_FRAG_TEX', 2: 'SB_VERT_MIPADDR',
      3: 'SB_FRAG_MIPADDR', 4: 'SB_VERT_SHADER', 6: 'SB_FRAG_SHADER'}
SS = {0: 'SS_DIRECT', 2: 'SS_INVALID_ALL_IC', 3: 'SS_INVALID_PART_IC',
      4: 'SS_INDIRECT', 5: 'SS_INDIRECT_STM'}
ST = {0: 'ST_SHADER', 1: 'ST_CONSTANTS'}
CP_LOAD_STATE = 0x30

ASCII85_LINE = re.compile(r'[!-uz]+\Z')


def payloads(path):
    """Yield (label, decoded bytes) for every ascii85 block in the dump."""
    iova = size = None
    label = None
    chunks = None
    for line in open(path, 'r', errors='replace'):
        line = line.rstrip('\n')
        m = re.match(r'\s*-?\s*iova: (0x[0-9a-f]+)', line)
        if m:
            iova = m.group(1)
        m = re.match(r'\s*size: (\d+)', line)
        if m:
            size = int(m.group(1))
        if 'data: !!ascii85' in line:
            if chunks:
                yield label, chunks
            label = '%s size=%s' % (iova, size)
            chunks = []
            continue
        if chunks is None:
            continue
        stripped = line.strip()
        if stripped and ASCII85_LINE.match(stripped):
            chunks.append(stripped)
        else:
            yield label, chunks
            chunks = None
    if chunks:
        yield label, chunks


def dwords(chunks):
    raw = base64.a85decode(''.join(chunks))
    return [int.from_bytes(raw[i:i + 4], 'big')
            for i in range(0, len(raw) - 3, 4)]


def scan(dw):
    """Yield decoded CP_LOAD_STATE fields found in a payload.

    This tests every dword as a candidate packet header rather than walking
    the packet stream, because a dumped buffer object need not begin on a
    packet boundary and one bogus type-3 header with a large count would
    otherwise skip the rest of the buffer. A hit's body is skipped, so
    constants that happen to look like headers do not produce duplicates.
    False positives are possible in payloads that are pure data; judge a hit
    by whether its fields are sane and by how it sits among its neighbours.
    """
    i = 0
    while i < len(dw) - 2:
        header = dw[i]
        if (header & 0xC0000000) != 0xC0000000 or \
                ((header >> 8) & 0xFF) != CP_LOAD_STATE:
            i += 1
            continue
        count = ((header >> 16) & 0x3FFF) + 1
        d0, d1 = dw[i + 1], dw[i + 2]
        yield {
            'off': i * 4,
            'count': count,
            'dst_off': d0 & 0xFFFF,
            'src': (d0 >> 16) & 0x7,
            'block': (d0 >> 19) & 0x7,
            'num_unit': (d0 >> 22) & 0x3FF,
            'type': d1 & 0x3,
            'addr': d1 & ~3,
        }
        i += 1 + count


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    path = argv[1]
    show_all = '--all' in argv[2:]

    for line in open(path, 'r', errors='replace'):
        if re.match(r'(kernel|module|comm|cmdline|revision|rbbm-status):', line):
            sys.stdout.write(line)
        if re.match(r'\s+(last-fence|retired-fence|rptr|wptr):', line):
            sys.stdout.write(line)
        if line.startswith('bos:'):
            break

    fs_indirect_const = vs_indirect_const = total = 0
    undecodable = []
    for label, chunks in payloads(path):
        try:
            dw = dwords(chunks)
        except Exception as exc:                        # noqa: BLE001
            undecodable.append('%s (%s)' % (label, exc))
            continue
        hits = list(scan(dw))
        if not hits:
            continue
        printed = False
        for h in hits:
            total += 1
            is_const = h['type'] == 1 and h['src'] == 4
            if is_const and h['block'] == 6:
                fs_indirect_const += 1
            elif is_const and h['block'] == 4:
                vs_indirect_const += 1
            elif not show_all:
                continue
            if not printed:
                print('== %s dwords=%d CP_LOAD_STATE=%d'
                      % (label, len(dw), len(hits)))
                printed = True
            print('   +0x%06x cnt=%-4d dst_off=%-4d %-16s %-16s num_unit=%-4d '
                  '%-12s src_addr=0x%08x'
                  % (h['off'], h['count'], h['dst_off'],
                     SS.get(h['src'], str(h['src'])),
                     SB.get(h['block'], str(h['block'])),
                     h['num_unit'], ST.get(h['type'], str(h['type'])),
                     h['addr']))

    print()
    print('CP_LOAD_STATE packets:            %d' % total)
    print('  SS_INDIRECT SB_FRAG_SHADER ST_CONSTANTS: %d' % fs_indirect_const)
    print('  SS_INDIRECT SB_VERT_SHADER ST_CONSTANTS: %d' % vs_indirect_const)
    for entry in undecodable:
        print('undecodable payload, not scanned: %s' % entry)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
