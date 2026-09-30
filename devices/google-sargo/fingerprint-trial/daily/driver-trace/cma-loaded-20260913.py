#!/usr/bin/python3
"""CMA baseline after loading the FPC app; no sensor commands or credentials."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import time

ROOT = Path('/var/tmp/sargo-fingerprint-cma-loaded-20260913')
BOOT = '958f6ac0-f6a3-4b7e-815d-875c2a9a948d'
HEAP = Path('/dev/dma_heap/default_cma_region')
COUNT = 1000
SIZE = 8192

def out(*args):
    return subprocess.check_output(args, text=True).strip()

def save(name, data):
    with (ROOT / name).open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())

os.umask(0o077)
assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
assert 'androidboot.serialno=994AY18RSD' in Path('/proc/cmdline').read_text().split()
assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert out('getenforce') == 'Enforcing'
assert hashlib.sha256(Path('/etc/pam.d/phosh').read_bytes()).hexdigest() == '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
assert stat.S_ISCHR(HEAP.stat().st_mode)
for unit in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service'):
    assert os.readlink(Path('/etc/systemd/system') / unit) == '/dev/null'
for unit in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'qsee-supplicant.service',
             'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service'):
    assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
assert not Path('/sys/kernel/tracing/kprobe_events').read_text().strip()
assert not list(Path('/sys/kernel/tracing/instances').iterdir())

# include/uapi/linux/dma-heap.h: _IOWR('H', 0, struct dma_heap_allocation_data).
# ARM64 uses the asm-generic ioctl encoding and this structure is 24 bytes.
layout = struct.Struct('=QIIQ')
assert layout.size == 24
allocate = (3 << 30) | (layout.size << 16) | (ord('H') << 8)
report = {'boot_id': BOOT, 'serial': '994AY18RSD', 'heap': str(HEAP),
          'planned_allocations': COUNT, 'bytes_per_allocation': SIZE,
          'completed': 0, 'tee_calls_by_allocator': False, 'sensor_opened': False,
          'kernel_tracing': False, 'coherent_mapping_tested': False,
          'firmware_loads': True, 'sensor_commands_issued': False, 'loaded_units': []}
save('attempt.json', report)
start = time.monotonic()
print('FPC_CMA_LOADED_BEGIN ' + json.dumps(report), flush=True)
loaders = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
           'qsee-app-loader@fpctzappfingerprint.service')
try:
    for unit in loaders:
        print('FPC_CMA_LOADED_START ' + unit, flush=True)
        subprocess.run(['systemctl', 'start', unit], check=True)
        report['loaded_units'].append(unit)
    heap_fd = os.open(HEAP, os.O_RDONLY | os.O_CLOEXEC)
    try:
        for number in range(1, COUNT + 1):
            request = bytearray(layout.pack(SIZE, 0, os.O_RDWR | os.O_CLOEXEC, 0))
            fcntl.ioctl(heap_fd, allocate, request, True)
            size, buffer_fd, flags, heap_flags = layout.unpack(request)
            # Closing releases only this request's new buffer. Never map or
            # inspect its contents, or touch buffers belonging to other users.
            os.close(buffer_fd)
            report['completed'] = number
            if number % 100 == 0:
                print(f'FPC_CMA_LOADED_PROGRESS completed={number}', flush=True)
            time.sleep(0.005)
    finally:
        os.close(heap_fd)
except Exception as error:
    report['error'] = repr(error)
for unit in reversed(report['loaded_units']):
    print('FPC_CMA_LOADED_STOP ' + unit, flush=True)
    subprocess.run(['systemctl', 'stop', unit], check=True)
report['clean_shutdown'] = True
report['elapsed_seconds'] = time.monotonic() - start
report['passed'] = report['completed'] == COUNT and 'error' not in report
print('FPC_CMA_LOADED_RESULT ' + json.dumps(report), flush=True)
save('result.json', report)
