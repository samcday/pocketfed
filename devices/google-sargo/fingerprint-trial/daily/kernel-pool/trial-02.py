#!/usr/bin/python3
"""One disposable INIT/CMA/DEEP_SLEEP comparison on daily sam-sargo (generation 02).

Identical to trial.py except: new run identifiers, an explicit read-only
vendor_b mapping step before firmware staging, and firmware/mapping receipts
in the report. No capture, enrollment, credential or recovery API is called.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/run/sargo-fingerprint-pool-20260913')
CODE = Path(__file__).resolve().parent
VENDOR_UNIT = 'pocketfed-fpc-pool-vendor-b.service'
FIRMWARE_UNIT = 'pocketfed-fpc-pool-firmware.service'
LOADERS = ('pocketfed-fpc-pool-supp.service', 'pocketfed-fpc-pool-cmnlib.service',
           'pocketfed-fpc-pool-fpc.service')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def save(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def unit_state(unit):
    return {key: out('systemctl', 'show', unit, '-p', key, '--value')
            for key in ('ActiveState', 'Result', 'ExecMainStatus')}


os.umask(0o077)
assert os.geteuid() == 0
args = Path('/proc/cmdline').read_text().split()
assert 'androidboot.serialno=994AY18RSD' in args
assert 'pocketfed.root_mode=usb' in args
runs = [x.split('=', 1)[1] for x in args if x.startswith('pocketfed.liveboot=')]
assert len(runs) == 1
mode = {'sargo-fingerprint-pool-baseline-02-20260913': 'N',
        'sargo-fingerprint-pool-reuse-02-20260913': 'Y'}[runs[0]]
assert out('findmnt', '-n', '-o', 'FSTYPE', '/') == 'overlay'
assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert out('getenforce') == 'Enforcing'
assert b'google,sargo' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
manifest = json.loads((CODE / 'manifest.json').read_text())
assert hashlib.sha256((CODE / 'initialize').read_bytes()).hexdigest() == manifest['probe_sha256']
assert hashlib.sha256((CODE / 'map-vendor-b.py').read_bytes()).hexdigest() == manifest['mapper_sha256']
for unit in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service',
             'pocketfed-keymaster-startup.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'):
    assert os.readlink(Path('/etc/systemd/system') / unit) == '/dev/null', unit
for unit in (VENDOR_UNIT, FIRMWARE_UNIT, *LOADERS):
    assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
assert not os.path.lexists('/dev/mapper/vendor_b')
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
    # Read-only slot-b vendor mapping from revalidated metadata; no writes.
    print('FPC_POOL_START ' + VENDOR_UNIT, flush=True)
    vendor = subprocess.run(['systemctl', 'start', VENDOR_UNIT])
    report['vendor_b_unit'] = unit_state(VENDOR_UNIT)
    receipt = Path('/run/pocketfed-fpc-pool-vendor-b/receipt.json')
    if receipt.is_file():
        data = json.loads(receipt.read_text())
        report['vendor_b'] = {key: data.get(key) for key in
                              ('observed', 'ext4', 'dm_table_applied', 'block_read_only',
                               'vendor_build', 'lpdump_agrees', 'result')}
    if vendor.returncode:
        raise RuntimeError('vendor_b mapping refused; see FPC_POOL_VENDOR_B_REFUSED')
    # This copies hash-pinned program firmware into the disposable root only.
    print('FPC_POOL_START ' + FIRMWARE_UNIT, flush=True)
    firmware = subprocess.run(['systemctl', 'start', FIRMWARE_UNIT])
    report['firmware_unit'] = unit_state(FIRMWARE_UNIT)
    journal = out('journalctl', '-u', FIRMWARE_UNIT, '-o', 'cat', '--no-pager')
    for line in reversed(journal.splitlines()):
        if line.startswith('{') and '"bundle_sha256"' in line:
            report['firmware'] = json.loads(line)
            break
    if firmware.returncode:
        raise RuntimeError('firmware staging failed')
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
