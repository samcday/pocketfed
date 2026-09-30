#!/usr/bin/python3
"""Check post-reboot Gatekeeper verification and FPC enrollment authorization."""
import hashlib
import json
from pathlib import Path
import resource
import subprocess
from lab_report import emit

resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
HERE = Path(__file__).resolve().parent
RUN = 'sargo-fingerprint-lab-authorization-20260911'
PREFIX = 'pocketfed-fingerprint-lab-'
report = {'serial': '99NAY1AZG1', 'run_id': RUN, 'linux_uid': 1234,
          'rpmb_writes': True, 'gatekeeper_enrollment': False,
          'fingerprint_samples': False, 'fingerprint_database_access': False, 'steps': []}


def operation(action, name):
    unit = PREFIX + name + '.service'
    step = {'action': action, 'unit': unit}
    try:
        r = subprocess.run(['systemctl', action, unit], capture_output=True, timeout=90)
        step['status'] = r.returncode
    except subprocess.TimeoutExpired:
        step['observation_timeout'] = True
    step['state'] = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
        '-p', 'SubState', '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'], text=True).splitlines()
    report['steps'].append(step)
    emit('authorization_' + action + '_' + name, step)
    if step.get('status') != 0:
        raise RuntimeError('operation did not complete successfully: ' + unit)


try:
    tokens = Path('/proc/cmdline').read_text().split()
    assert 'androidboot.serialno=99NAY1AZG1' in tokens
    assert 'pocketfed.root_mode=usb' in tokens and 'pocketfed.liveboot=' + RUN in tokens
    metadata = json.loads((HERE / 'authorization.json').read_text())
    assert metadata['serial'] == report['serial'] and metadata['run_id'] == RUN
    credential = Path('/var/lib/pocketfed-fpc-auth/uid-1234.credential')
    assert hashlib.sha256(credential.read_bytes()).hexdigest() == metadata['credential_sha256']
    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster', 'authorization'):
        operation('start', name)
    assert hashlib.sha256(credential.read_bytes()).hexdigest() == metadata['credential_sha256']
    for name in ('authorization', 'keymaster', 'fpc', 'cmnlib', 'rpmb'):
        operation('stop', name)
    report['result'] = 'retained credential verified after reboot; FPC authorized enrollment; clean service shutdown'
except Exception as error:
    report['error'] = str(error)
finally:
    report['events'] = {}
    for name in ('rpmb', 'cmnlib', 'fpc', 'keymaster', 'authorization'):
        log = subprocess.check_output(['journalctl', '-b', '-u', PREFIX + name + '.service',
                                       '-o', 'cat', '--no-pager'], text=True)
        prefixes = ('event=', 'lab_', 'wrapped_key ', 'get_hmac_parameters ',
                    'compute_shared_hmac ', 'sharing_check_length=', 'hmac_state=', 'initialization_status=')
        report['events'][name] = [s for s in log.splitlines() if s.startswith(prefixes)]
    emit('authorization_finished', report)
