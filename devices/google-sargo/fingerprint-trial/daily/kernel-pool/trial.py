#!/usr/bin/python3
"""One disposable INIT/CMA/DEEP_SLEEP comparison on daily sam-sargo."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/run/sargo-fingerprint-pool-20260913')
CODE = Path(__file__).resolve().parent
LOADERS = ('pocketfed-fpc-pool-supp.service', 'pocketfed-fpc-pool-cmnlib.service',
           'pocketfed-fpc-pool-fpc.service')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def save(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


os.umask(0o077)
assert os.geteuid() == 0
args = Path('/proc/cmdline').read_text().split()
assert 'androidboot.serialno=994AY18RSD' in args
assert 'pocketfed.root_mode=usb' in args
runs = [x.split('=', 1)[1] for x in args if x.startswith('pocketfed.liveboot=')]
assert len(runs) == 1
mode = {'sargo-fingerprint-pool-baseline-20260913': 'N',
        'sargo-fingerprint-pool-reuse-20260913': 'Y'}[runs[0]]
assert out('findmnt', '-n', '-o', 'FSTYPE', '/') == 'overlay'
assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert out('getenforce') == 'Enforcing'
assert b'google,sargo' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
manifest = json.loads((CODE / 'manifest.json').read_text())
assert hashlib.sha256((CODE / 'initialize').read_bytes()).hexdigest() == manifest['probe_sha256']
for unit in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service',
             'pocketfed-keymaster-startup.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'):
    assert os.readlink(Path('/etc/systemd/system') / unit) == '/dev/null', unit
for unit in LOADERS:
    assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
assert not Path('/sys/kernel/tracing/kprobe_events').read_text().strip()
assert not list(Path('/sys/kernel/tracing/instances').iterdir())
ROOT.mkdir(mode=0o700)
(ROOT / 'cpu7').mkdir(mode=0o700)
report = {'run': runs[0], 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
          'serial': '994AY18RSD', 'reuse_invoke_pool': mode, 'started_units': [],
          'capture_requested': False, 'credential_operation_requested': False,
          'kernel_tracing': False, 'cpu_affinity': '7'}
save('attempt.json', report)
print('FPC_POOL_TRIAL_BEGIN ' + json.dumps(report), flush=True)
start = time.monotonic()
try:
    subprocess.run(['modprobe', 'qseecomtee'], check=True)
    assert Path('/sys/module/qseecomtee/parameters/reuse_invoke_pool').read_text().strip() == mode
    # This copies hash-pinned program firmware into the disposable root only.
    subprocess.run(['systemctl', 'start', 'pocketfed-fpc-pool-firmware.service'], check=True)
    for unit in LOADERS:
        print('FPC_POOL_START ' + unit, flush=True)
        subprocess.run(['systemctl', 'start', unit], check=True)
        report['started_units'].append(unit)
    # No timeout or forced cancellation of an in-flight secure call.
    report['native_exit_status'] = subprocess.run([str(CODE / 'initialize'), '--cpu=7']).returncode
except Exception as error:
    report['error'] = repr(error)
for unit in reversed(report['started_units']):
    print('FPC_POOL_STOP ' + unit, flush=True)
    subprocess.run(['systemctl', 'stop', unit], check=True)
report['elapsed_seconds'] = time.monotonic() - start
report['clean_shutdown'] = True
report['passed'] = report.get('native_exit_status') == 0 and 'error' not in report
save('result.json', report)
print('FPC_POOL_TRIAL_RESULT ' + json.dumps(report), flush=True)
