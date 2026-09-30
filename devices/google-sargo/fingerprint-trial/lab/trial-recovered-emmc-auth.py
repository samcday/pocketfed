#!/usr/bin/python3
"""Verify both retained lab records after recovery during read-only eMMC load."""
from pathlib import Path
import hashlib
import json
import subprocess
import time
import threading
import stat
import os
from lab_report import emit

RUN = 'sargo-fingerprint-lab-recovered-emmc-auth-20260912'
HERE = Path(__file__).resolve().parent
UNITS = ['pocketfed-fingerprint-lab-firmware.service', 'qsee-supplicant.service',
         'qsee-shared-loader@cmnlib64.service', 'qsee-app-loader@fpctzappfingerprint.service',
         'pocketfed-keymaster-startup.service', 'pocketfed-fpc-native-auth-probe.service']
report = {'run_id': RUN, 'serial': '99NAY1AZG1', 'linux_uid': 1000,
          'enrollment': False, 'credential_export': False, 'linux_uids': [1000, 1234], 'steps': []}
guarded = False
load_thread = None
load_stop = threading.Event()
load_ready = threading.Event()
load = {'partition': 'mmcblk0p2', 'partlabel': 'xbl_a', 'read_only': True,
        'direct_io': True, 'bytes_per_iteration': 2097152, 'iterations': 0}


def read_load():
    """Only the observed signed-program XBL partition; no credential partitions."""
    try:
        dev = Path('/dev/mmcblk0p2')
        assert stat.S_ISBLK(dev.stat().st_mode)
        props = dict(line.split('=', 1) for line in
                     Path('/sys/class/block/mmcblk0p2/uevent').read_text().splitlines())
        assert props['PARTNAME'] == 'xbl_a' and props['DEVNAME'] == 'mmcblk0p2'
        assert int(Path('/sys/class/block/mmcblk0p2/size').read_text()) * 512 >= 2097152
        mount = subprocess.run(['findmnt', '-rn', '-S', str(dev)], capture_output=True, text=True)
        assert mount.returncode == 1 and mount.stdout == ''
        load['start_monotonic'] = time.monotonic()
        deadline = load['start_monotonic'] + 60
        while not load_stop.is_set() and time.monotonic() < deadline:
            # O_DIRECT bypasses page cache; discard all program bytes. No writes.
            result = subprocess.run(['dd', 'if=' + str(dev), 'of=/dev/null',
                'bs=512K', 'count=4', 'iflag=direct', 'status=none'],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if result.returncode:
                raise RuntimeError('read workload status=' + str(result.returncode) + ': ' + result.stderr.strip())
            load['iterations'] += 1
            load_ready.set()
        load['end_monotonic'] = time.monotonic()
    except Exception as error:
        load['error'] = str(error)
        load_ready.set()



def operation(action, unit):
    # Each checksummed record name identifies one immutable operation.
    emit('native_auth_operation_' + chr(ord('a') + len(report['steps'])),
         {'action': action, 'unit': unit})
    # A synchronous secure call must finish; no forced timeout or restart.
    result = subprocess.run(['systemctl', action, unit], capture_output=True, text=True)
    state = subprocess.check_output(['systemctl', 'show', unit,
        '-p', 'ActiveState,SubState,Result,ExecMainStatus,NRestarts'], text=True).splitlines()
    report['steps'].append({'action': action, 'unit': unit, 'status': result.returncode, 'state': state})
    if result.returncode:
        raise RuntimeError(f'{action} {unit} failed: {result.stderr.strip()}')


try:
    assert 'pocketfed.liveboot=' + RUN in Path('/proc/cmdline').read_text().split()
    subprocess.run(['/usr/bin/python3', str(HERE / 'guard-device.py')], check=True)
    guarded = True
    assert subprocess.check_output(['getenforce'], text=True).strip() == 'Enforcing'
    expected = json.loads((HERE / 'authorization.json').read_text())['credential_hashes']
    assert set(expected) == {'1000', '1234'}
    for uid, digest in expected.items():
        assert hashlib.sha256(Path('/var/lib/pocketfed-fpc-auth/uid-' + uid + '.credential').read_bytes()).hexdigest() == digest
    Path('/run/pocketfed-fingerprint-lab/native-auth-launch').touch(exist_ok=False)
    subprocess.run(['systemctl', 'unmask', *UNITS[1:-1], 'qsee-app-loader@.service',
                    'qsee-shared-loader@.service'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    Path('/run/pocketfed-fingerprint-lab/normal-chain-ready').touch(exist_ok=False)
    for unit in UNITS[:-1]:
        operation('start', unit)
    load_thread = threading.Thread(target=read_load, name='read-only-xbl-load')
    load_thread.start()
    assert load_ready.wait(20), 'read workload did not become ready'
    assert 'error' not in load, load.get('error')
    assert load['iterations'] >= 1 and load_thread.is_alive()
    report['read_load_before_verify'] = dict(load)
    emit('native_auth_read_load_begin', dict(load))
    operation('start', UNITS[-1])
    report['read_load_after_verify'] = dict(load)
    assert 'error' not in load, load.get('error')
    assert load_thread.is_alive(), 'read workload ended before verification completed'
    assert load['iterations'] > report['read_load_before_verify']['iterations'], 'no completed concurrent reads'
    for uid, digest in expected.items():
        assert hashlib.sha256(Path('/var/lib/pocketfed-fpc-auth/uid-' + uid + '.credential').read_bytes()).hexdigest() == digest
    report['credential_unchanged'] = True
    report['result'] = 'recovered UID 1000 and original UID 1234 verified after reboot during direct eMMC reads'
except Exception as error:
    report['error'] = str(error)
finally:
    load_stop.set()
    if load_thread is not None:
        # Never terminate a potentially blocked kernel I/O; retain USB hosting.
        load_thread.join()
        report['read_load'] = dict(load)
    # Reached only after the synchronous start returned, never on observation timeout.
    if guarded:
        try:
            for unit in reversed(UNITS[1:]):
                operation('stop', unit)
            report['clean_shutdown'] = True
        except Exception as error:
            report['shutdown_error'] = str(error)
    report['events'] = {}
    for unit in ('pocketfed-fpc-native-auth-probe.service', 'qsee-supplicant.service',
                 'pocketfed-keymaster-startup.service'):
        report['events'][unit] = subprocess.check_output(
            ['journalctl', '-b', '-u', unit, '-o', 'cat', '--no-pager'], text=True).splitlines()
    emit('native_auth_finished', report)
