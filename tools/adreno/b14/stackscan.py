#!/usr/bin/env python3
"""Poor man's backtrace: for each thread of PID, read the stack from the
saved SP and print words that point into executable file mappings as
(thread, depth, path, file offset). Candidates only; symbolize offline."""
import sys

pid = int(sys.argv[1])
maxwords = int(sys.argv[2]) if len(sys.argv) > 2 else 4096

maps = []
for line in open(f'/proc/{pid}/maps'):
    parts = line.split()
    if len(parts) < 6 or 'x' not in parts[1]:
        continue
    lo, hi = (int(x, 16) for x in parts[0].split('-'))
    maps.append((lo, hi, int(parts[2], 16), parts[5]))


def lookup(addr):
    for lo, hi, off, path in maps:
        if lo <= addr < hi:
            return path, addr - lo + off
    return None


import os
mem = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
for tid in sorted(os.listdir(f'/proc/{pid}/task'), key=int):
    comm = open(f'/proc/{pid}/task/{tid}/comm').read().strip()
    sc = open(f'/proc/{pid}/task/{tid}/syscall').read().split()
    if len(sc) < 3:
        print(f'T {tid} {comm} running')
        continue
    sp, pc = int(sc[-2], 16), int(sc[-1], 16)
    hit = lookup(pc)
    print(f'T {tid} {comm} sys={sc[0]} pc={hit[0].rsplit("/", 1)[-1]}+{hit[1]:#x}' if hit else f'T {tid} {comm} sys={sc[0]} pc={pc:#x}')
    try:
        data = os.pread(mem, maxwords * 8, sp)
    except OSError:
        continue
    n = 0
    for i in range(0, len(data) - 7, 8):
        v = int.from_bytes(data[i:i + 8], 'little')
        hit = lookup(v)
        if hit:
            print(f'  {i // 8:5d} {hit[0].rsplit("/", 1)[-1]} {hit[1]:#x}')
            n += 1
            if n >= 40:
                break
