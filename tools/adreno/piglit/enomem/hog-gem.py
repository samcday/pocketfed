#!/usr/bin/env python3
"""hog-gem.py MIB [BO_KIB] -- msm GEM page hog (planning artefact, not yet run).

Mimics the other deqp-runner jobs' buffer churn without submitting any GPU work:
allocates msm GEM BOs of BO_KIB (default 16 KiB) on /dev/dri/renderD128, faults their
pages in through the GEM mmap offset, and every second closes a random 1/4 of them and
allocates replacements, holding ~MIB MiB.

Why GEM pages: msm_gem.c:1290 (5dd1818b15d9) sets the shmem mapping gfp to GFP_HIGHUSER
(no __GFP_MOVABLE), so they are MIGRATE_UNMOVABLE allocations, and drm_gem_get_pages()
(drm_gem.c:690) marks the mapping unevictable and holds page references, so compaction
cannot migrate them. Scattered across pageblocks they stop any pageblock from becoming a
free order-9 block -- the same kind of pages vbo-subdata-many and the concurrent GL tests
allocate in CI. No GPU submission => no hang risk from the hog itself.

uapi (include/uapi/drm/msm_drm.h @5dd1818b15d9): DRM_MSM_GEM_NEW 0x02 {u64 size; u32 flags;
u32 handle}, DRM_MSM_GEM_INFO 0x03 {u32 handle; u32 info; u64 value; u32 len; u32 pad},
MSM_INFO_GET_OFFSET 0, MSM_BO_WC 0x20000; drm.h DRM_IOCTL_GEM_CLOSE = DRM_IOW(0x09, {u32,u32}).
"""
import fcntl, mmap, os, random, struct, sys, time

def _IOC(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr

DRM_COMMAND_BASE = 0x40
GEM_NEW = _IOC(3, 'd', DRM_COMMAND_BASE + 0x02, 16)
GEM_INFO = _IOC(3, 'd', DRM_COMMAND_BASE + 0x03, 24)
GEM_CLOSE = _IOC(1, 'd', 0x09, 8)
MSM_BO_WC = 0x00020000
MSM_INFO_GET_OFFSET = 0

mib = int(sys.argv[1])
bo_kib = int(sys.argv[2]) if len(sys.argv) > 2 else 16
size = bo_kib * 1024
count = max(1, mib * 1024 // bo_kib)
fd = os.open("/dev/dri/renderD128", os.O_RDWR | os.O_CLOEXEC)

def new_bo():
    buf = bytearray(struct.pack("QII", size, MSM_BO_WC, 0))
    fcntl.ioctl(fd, GEM_NEW, buf)
    handle = struct.unpack("QII", buf)[2]
    info = bytearray(struct.pack("IIQII", handle, MSM_INFO_GET_OFFSET, 0, 0, 0))
    fcntl.ioctl(fd, GEM_INFO, info)
    off = struct.unpack("IIQII", info)[2]
    mm = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=off)
    for p in range(0, size, 4096):
        mm[p] = 1          # fault -> msm_gem_fault -> get_pages (whole BO)
    return handle, mm

def free_bo(bo):
    handle, mm = bo
    mm.close()             # drop the vma's object reference first
    fcntl.ioctl(fd, GEM_CLOSE, struct.pack("II", handle, 0))

bos = [new_bo() for _ in range(count)]
print(f"hog-gem: holding {count} x {bo_kib} KiB = {count * bo_kib // 1024} MiB", flush=True)
while True:
    for i in random.sample(range(count), count // 4):
        free_bo(bos[i])
        bos[i] = new_bo()
    time.sleep(1)
