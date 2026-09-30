#!/usr/bin/python3
"""One INIT -> CMA allocations -> DEEP_SLEEP comparison; no capture or credentials."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

ROOT = Path('/var/tmp/sargo-fingerprint-init-cma-20260913')
BOOT = '958f6ac0-f6a3-4b7e-815d-875c2a9a948d'
BINARY_SHA = '488a2e8127817179baa8080463118d59524633cdae7080df39ec463a50028ab8'
LOADERS = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
           'qsee-app-loader@fpctzappfingerprint.service')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def save(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


os.umask(0o077)
assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
assert ROOT.stat().st_uid == 0 and stat.S_IMODE(ROOT.stat().st_mode) == 0o700
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
assert 'androidboot.serialno=994AY18RSD' in Path('/proc/cmdline').read_text().split()
assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert out('getenforce') == 'Enforcing'
assert hashlib.sha256(Path('/etc/pam.d/phosh').read_bytes()).hexdigest() == '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
assert hashlib.sha256((ROOT / 'init-cma-20260913').read_bytes()).hexdigest() == BINARY_SHA
for unit in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service'):
    assert os.readlink(Path('/etc/systemd/system') / unit) == '/dev/null'
for unit in (*LOADERS, 'fprintd.service', 'phosh-fingerprint-auth.socket', 'pocketfed-keymaster-startup.service'):
    assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
assert not Path('/sys/kernel/tracing/kprobe_events').read_text().strip()
assert not list(Path('/sys/kernel/tracing/instances').iterdir())
assert stat.S_ISCHR(Path('/dev/dma_heap/default_cma_region').stat().st_mode)
report = {'boot_id': BOOT, 'serial': '994AY18RSD', 'binary_sha256': BINARY_SHA,
          'sequence': ['INIT', '1000 x 8192B CMA allocate/close', 'DEEP_SLEEP'],
          'capture_started': False, 'credentials_accessed': False,
          'kernel_tracing': False, 'cpu_affinity': '7', 'started_units': []}
save('attempt.json', report)
(ROOT / 'cpu7').mkdir(mode=0o700)
print('FPC_INIT_CMA_CONTROLLER_BEGIN ' + json.dumps(report), flush=True)
start = time.monotonic()
try:
    for unit in LOADERS:
        print('FPC_INIT_CMA_CONTROLLER_START ' + unit, flush=True)
        subprocess.run(['systemctl', 'start', unit], check=True)
        report['started_units'].append(unit)
    # A blocked synchronous driver call stays available for UART diagnosis.
    # There is no kill, timed retry, or additional sensor operation on failure.
    report['native_exit_status'] = subprocess.run([str(ROOT / 'init-cma-20260913'), '--cpu=7']).returncode
except Exception as error:
    report['error'] = repr(error)
for unit in reversed(report['started_units']):
    print('FPC_INIT_CMA_CONTROLLER_STOP ' + unit, flush=True)
    subprocess.run(['systemctl', 'stop', unit], check=True)
report['clean_shutdown'] = True
report['elapsed_seconds'] = time.monotonic() - start
report['passed'] = report.get('native_exit_status') == 0 and 'error' not in report
print('FPC_INIT_CMA_CONTROLLER_RESULT ' + json.dumps(report), flush=True)
save('result.json', report)
