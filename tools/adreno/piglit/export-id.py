#!/usr/bin/env python3
# smoo-host export id: FNV-1a32 over u32 block_size LE, u64 block_count LE, "file:<canonical path>"
import os, struct, sys
def eid(path, bs=512):
    p = os.path.realpath(path)
    data = struct.pack('<I', bs) + struct.pack('<Q', os.path.getsize(p) // bs) + ('file:' + p).encode()
    h = 0x811c9dc5
    for b in data:
        h ^= b; h = (h * 0x01000193) & 0xffffffff
    return h or 1
for p in sys.argv[1:]:
    print(eid(p), p)
