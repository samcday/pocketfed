#!/usr/bin/env python3
"""Prepend an RD_GPU_ID section to a Mesa-written .rd so cffdump can decode it.

A Mesa .rd carries only RD_CHIP_ID.  For a3xx fd_dev_info_raw() returns NULL
for that, cffdec_init() is skipped, rnn stays NULL and cffdump segfaults.

usage: add-rd-gpuid.py <in.rd|in.rd.gz> <out.rd>
"""
import struct, sys, gzip, os
src, dst = sys.argv[1], sys.argv[2]
d = open(src,'rb').read()
if d[:2] == b'\x1f\x8b':
    d = gzip.decompress(d)
hdr = struct.pack('<II', 13, 4) + struct.pack('<I', 307)   # RD_GPU_ID = 307
open(dst,'wb').write(hdr + d)
print('wrote', dst, len(hdr)+len(d))
