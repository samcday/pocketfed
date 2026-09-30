#!/usr/bin/python3
"""One credential attempt with read-only RPMB and encrypted host result export."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import subprocess
from lab_report import emit

os.umask(0o077)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

HERE = Path(__file__).resolve().parent
PREFIX = 'pocketfed-fingerprint-lab-'
RUN = 'sargo-fingerprint-lab-gatekeeper-ro-20260911'
report = {'serial': '99NAY1AZG1', 'run_id': RUN, 'rpmb_writes': False,
          'linux_uid': 1234, 'steps': [], 'encrypted_credential': None}


def encrypt(data):
    result = subprocess.run([str(HERE / 'encrypt-record'), str(HERE / 'export-public.pem')],
                            input=data, capture_output=True, timeout=20)
    assert result.returncode == 0 and len(result.stdout) == 384, 'encrypted export preflight/result failed'
    return result.stdout


def operation(action, name):
    unit = PREFIX + name + '.service'
    step = {'action': action, 'unit': unit}
    try:
        result = subprocess.run(['systemctl', action, unit], capture_output=True, timeout=90)
        step['status'] = result.returncode
    except subprocess.TimeoutExpired:
        step['observation_timeout'] = True
    step['state'] = subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
        '-p', 'SubState', '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'], text=True).splitlines()
    report['steps'].append(step)
    emit('gatekeeper_' + action + '_' + name, step)
    if step.get('status') != 0:
        raise RuntimeError('operation did not complete successfully: ' + unit)


try:
    cmdline = Path('/proc/cmdline').read_text().split()
    assert 'androidboot.serialno=99NAY1AZG1' in cmdline
    assert 'pocketfed.liveboot=' + RUN in cmdline
    assert 'pocketfed.root_mode=usb' in cmdline
    metadata = json.loads((HERE / 'enrollment.json').read_text())
    assert metadata['serial'] == report['serial'] and metadata['run_id'] == RUN
    assert metadata['linux_uid'] == 1234
    assert hashlib.sha256((HERE / 'export-public.pem').read_bytes()).hexdigest() == metadata['public_key_sha256']
    # Establish that the export executable/key work before any secure operation.
    encrypt(bytes(160))
    intent = Path('/var/lib/pocketfed-fpc-auth/uid-1234.intent')
    assert hashlib.sha256(intent.read_bytes()).hexdigest() == metadata['intent_sha256']
    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster', 'enroll'):
        operation('start', name)
    credential = Path('/var/lib/pocketfed-fpc-auth/uid-1234.credential')
    info = credential.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == info.st_gid == 0
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and info.st_size == 160
    report['encrypted_credential'] = base64.b64encode(encrypt(credential.read_bytes())).decode()
    # Export immediately; if shutdown later stalls the encrypted result remains
    # retrievable. The host accepts only records matching its retained secret.
    emit('gatekeeper_credential', {'serial': report['serial'], 'run_id': RUN,
                                  'encrypted_credential': report['encrypted_credential']})
    for name in ('enroll', 'keymaster', 'fpc', 'cmnlib', 'rpmb'):
        operation('stop', name)
    report['result'] = 'credential committed and encrypted export available'
except Exception as error:
    report['error'] = str(error)
    # No retry and no forced termination after an uncertain synchronous call.
finally:
    report['events'] = {}
    for name in ('rpmb', 'cmnlib', 'fpc', 'keymaster', 'enroll'):
        text = subprocess.check_output(['journalctl', '-b', '-u', PREFIX + name + '.service',
                                        '-o', 'cat', '--no-pager'], text=True)
        prefixes = ('event=', 'wrapped_key ', 'get_hmac_parameters ', 'compute_shared_hmac ',
                    'sharing_check_length=', 'hmac_state=', 'initialization_status=', 'lab_')
        report['events'][name] = [line for line in text.splitlines() if line.startswith(prefixes)]
    emit('gatekeeper_finished', report)
