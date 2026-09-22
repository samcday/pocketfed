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

The summary separates vertex and fragment constant loads. Finding either
packet is evidence of the upload path, not proof that it caused the hang.

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


def payloads(path):
    """Yield (label, encoded chunks) for each YAML ascii85 literal block."""
    iova = size = None
    label = None
    chunks = None
    header_indent = content_indent = None
    with open(path, 'r', errors='replace') as stream:
        for line in stream:
            line = line.rstrip('\n')
            indent = len(line) - len(line.lstrip(' '))
            if chunks is not None:
                # Literal blocks end on dedent, not on characters outside the
                # ascii85 alphabet: YAML keys such as "bos:" and "registers:"
                # themselves consist entirely of valid ascii85 characters.
                if not line.strip():
                    continue
                if content_indent is None and indent > header_indent:
                    content_indent = indent
                if content_indent is not None and indent >= content_indent:
                    chunks.append(line[content_indent:])
                    continue
                yield label, chunks
                chunks = None

            m = re.match(r'\s*-?\s*iova: (0x[0-9a-f]+)', line)
            if m:
                iova = m.group(1)
            m = re.match(r'\s*size: (\d+)', line)
            if m:
                size = int(m.group(1))
            if re.match(r'\s*data: !!ascii85 \|\s*$', line):
                label = '%s size=%s' % (iova, size)
                chunks = []
                header_indent = indent
                content_indent = None
    if chunks is not None:
        yield label, chunks


def dwords(chunks):
    encoded = re.sub(r'[ \t\n\r\v\f]', '', ''.join(chunks))
    raw = base64.a85decode(encoded)
    # msm emits whole u32s: five digits, or the zero-word shorthand "z".
    # a85decode silently discards a lone final digit, so decoded length alone
    # cannot detect every truncated word. It validates "z" placement above.
    if len(encoded.replace('z', '')) % 5 or len(raw) % 4:
        raise ValueError('ascii85 payload ends with an incomplete 32-bit word')
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
        if count < 2 or i + 1 + count > len(dw):
            i += 1
            continue
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

    with open(path, 'r', errors='replace') as stream:
        for line in stream:
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
