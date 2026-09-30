#!/usr/bin/python3
"""Trace one real lab credential verification with the packaged service chain."""
from pathlib import Path
import hashlib
import json
import subprocess
import time
from lab_report import emit

RUN = 'sargo-fingerprint-lab-native-idle-auth-20260912'
HERE = Path(__file__).resolve().parent
UNITS = ['pocketfed-fingerprint-lab-firmware.service', 'qsee-supplicant.service',
         'qsee-shared-loader@cmnlib64.service', 'qsee-app-loader@fpctzappfingerprint.service',
         'pocketfed-keymaster-startup.service', 'pocketfed-fpc-native-auth-probe.service']
report = {'run_id': RUN, 'serial': '99NAY1AZG1', 'linux_uid': 1000,
          'enrollment': False, 'credential_export': False, 'steps': []}
guarded = False


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
    credential = Path('/var/lib/pocketfed-fpc-auth/uid-1000.credential')
    expected = json.loads((HERE / 'authorization.json').read_text())['credential_sha256']
    assert hashlib.sha256(credential.read_bytes()).hexdigest() == expected
    Path('/run/pocketfed-fingerprint-lab/native-auth-launch').touch(exist_ok=False)
    subprocess.run(['systemctl', 'unmask', *UNITS[1:-1], 'qsee-app-loader@.service',
                    'qsee-shared-loader@.service'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    Path('/run/pocketfed-fingerprint-lab/normal-chain-ready').touch(exist_ok=False)
    for unit in UNITS[:-1]:
        operation('start', unit)
    def power_state():
        result = {}
        for base in ('/sys/class/block/mmcblk0/device/power', '/sys/class/mmc_host/mmc0/device/power'):
            result[base] = {}
            for name in ('runtime_status', 'control', 'autosuspend_delay_ms', 'runtime_active_time', 'runtime_suspended_time'):
                try:
                    result[base][name] = (Path(base) / name).read_text().strip()
                except OSError as error:
                    result[base][name] = 'unavailable errno=' + str(error.errno)
        return result
    report['idle_before'] = power_state()
    emit('native_auth_idle_begin', {'wait_seconds': 360, 'power': report['idle_before']})
    # Exceed the daily startup-to-recovery interval without another secure call.
    time.sleep(360)
    report['idle_after'] = power_state()
    emit('native_auth_idle_end', {'wait_seconds': 360, 'power': report['idle_after']})
    operation('start', UNITS[-1])
    assert hashlib.sha256(credential.read_bytes()).hexdigest() == expected
    report['credential_unchanged'] = True
    report['result'] = 'existing native lab credential verified through packaged service chain'
except Exception as error:
    report['error'] = str(error)
finally:
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
