#!/usr/bin/python3
"""Start and stop one read-only receiver lifetime; no app or credential calls."""
import subprocess
from lab_report import emit

unit = 'pocketfed-fingerprint-lab-rpmb.service'
report = {'operations': ['start read-only receiver', 'inspect readiness', 'stop receiver'],
          'credential_operations': False, 'app_loads': False}


def show():
    return subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'SubState',
                                    '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'], text=True).splitlines()


try:
    result = subprocess.run(['systemctl', 'start', unit], capture_output=True, text=True, timeout=60)
    report['start_status'] = result.returncode
    report['after_start'] = show()
    emit('receiver_started', report)
    if result.returncode == 0:
        result = subprocess.run(['systemctl', 'stop', unit], capture_output=True, text=True, timeout=60)
        report['stop_status'] = result.returncode
        report['after_stop'] = show()
except subprocess.TimeoutExpired:
    report['observation_timeout'] = True
    report['state_after_timeout'] = show()
finally:
    log = subprocess.check_output(['journalctl', '-b', '-u', unit, '-o', 'cat', '--no-pager'], text=True)
    report['events'] = [line for line in log.splitlines()
                        if line.startswith(('event=', 'RPMB startup validation failed.'))]
    emit('receiver_finished', report)
