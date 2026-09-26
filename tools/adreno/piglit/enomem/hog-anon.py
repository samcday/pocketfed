#!/usr/bin/env python3
"""hog-anon.py MIB -- movable-memory pressure hog (planning artefact, not yet run).

Holds MIB of private anonymous memory (4 KiB pages; THP is madvise-only on Fedora, and this
never madvises HUGEPAGE) and every second discards and re-faults a random 1/8 of it.
Anonymous pages are MIGRATE_MOVABLE and migratable, so compaction can still assemble an
order-9 block around them: this is the "memory pressure without pinned fragmentation" arm.
"""
import mmap, random, sys, time

mib = int(sys.argv[1])
P = 4096
n = mib * 256
m = mmap.mmap(-1, n * P, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
for i in range(n):
    m[i * P] = 1
print(f"hog-anon: holding {mib} MiB ({n} pages)", flush=True)
while True:
    for i in random.sample(range(n), n // 8):
        m.madvise(mmap.MADV_DONTNEED, i * P, P)
    for i in range(n):
        m[i * P] = 1
    time.sleep(1)
