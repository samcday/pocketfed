#!/usr/bin/python3
"""Recover the existing test-sargo native UID using the frozen daily binary."""
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
RUN = 'sargo-fingerprint-lab-native-recovery-20260912'
HERE = Path(__file__).resolve().parent
UNITS = ['pocketfed-fingerprint-lab-firmware.service', 'qsee-supplicant.service',
         'qsee-shared-loader@cmnlib64.service', 'qsee-app-loader@fpctzappfingerprint.service',
         'pocketfed-keymaster-startup.service', 'pocketfed-fpc-native-recovery-probe.service']
report = {'run_id': RUN, 'serial': '99NAY1AZG1', 'linux_uid': 1000,
          'gatekeeper_uid': '0x700003e8', 'gatekeeper_enrollment': True,
          'fingerprint_enrollment': False, 'existing_native_record_recovery': True, 'steps': []}
guarded = False


def encrypt(data):
    r = subprocess.run([str(HERE / 'encrypt-record'), str(HERE / 'export-public.pem')],
                       input=data, capture_output=True, timeout=20)
    assert r.returncode == 0 and len(r.stdout) == 384
    return base64.b64encode(r.stdout).decode()


def operation(action, unit):
    emit('native_enroll_operation_' + chr(ord('a') + len(report['steps'])),
         {'action': action, 'unit': unit})
    # Observe synchronous secure calls to completion; never force a retry.
    r = subprocess.run(['systemctl', action, unit], capture_output=True, text=True)
    state = subprocess.check_output(['systemctl', 'show', unit,
        '-p', 'ActiveState,SubState,Result,ExecMainStatus,NRestarts'], text=True).splitlines()
    report['steps'].append({'action': action, 'unit': unit, 'status': r.returncode, 'state': state})
    if r.returncode:
        raise RuntimeError(f'{action} {unit} failed: {r.stderr.strip()}')


try:
    assert 'pocketfed.liveboot=' + RUN in Path('/proc/cmdline').read_text().split()
    subprocess.run(['/usr/bin/python3', str(HERE / 'guard-device.py')], check=True)
    guarded = True
    assert subprocess.check_output(['getenforce'], text=True).strip() == 'Enforcing'
    metadata = json.loads((HERE / 'native-enroll.json').read_text())
    assert metadata['run_id'] == RUN and metadata['serial'] == report['serial']
    assert metadata['linux_uid'] == 1000 and metadata['gatekeeper_uid'] == '0x700003e8'
    state = Path('/var/lib/pocketfed-fpc-auth')
    intent = state / 'uid-1000.intent'
    credential = state / 'uid-1000.credential'
    assert not credential.exists()
    assert metadata['recovery_binary_sha256'] == 'c36459ccbca8ceb6fed8b745c3817659ae3ebd71af164eff801dde94bbcccb22'
    assert hashlib.sha256(Path('/usr/bin/pocketfed-fpc-auth').read_bytes()).hexdigest() == metadata['recovery_binary_sha256']
    assert not (state / 'uid-1000.storage-recovery-attempt').exists()
    assert not (state / 'uid-1000.pre-storage-recovery.intent').exists()
    assert (state / 'uid-1000.first-recovery-attempt').read_text() == metadata['synthetic_prior_receipt']
    assert hashlib.sha256(intent.read_bytes()).hexdigest() == metadata['intent_sha256']
    old = state / 'uid-1234.credential'
    old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    assert hashlib.sha256((HERE / 'export-public.pem').read_bytes()).hexdigest() == metadata['public_key_sha256']
    encrypt(bytes(160))
    Path('/run/pocketfed-fingerprint-lab/native-enroll-launch').touch(exist_ok=False)
    subprocess.run(['systemctl', 'unmask', *UNITS[1:-1], 'qsee-app-loader@.service',
                    'qsee-shared-loader@.service'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    Path('/run/pocketfed-fingerprint-lab/normal-chain-ready').touch(exist_ok=False)
    for unit in UNITS:
        operation('start', unit)
    info = credential.lstat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_uid == info.st_gid == 0 and info.st_nlink == 1 and info.st_size == 160
    emit('native_enroll_credential', {'run_id': RUN, 'serial': report['serial'],
         'encrypted_credential': encrypt(credential.read_bytes())})
    assert hashlib.sha256(old.read_bytes()).hexdigest() == old_hash
    report['prior_lab_credential_unchanged'] = True
    assert hashlib.sha256((state / 'uid-1000.pre-storage-recovery.intent').read_bytes()).hexdigest() == metadata['intent_sha256']
    report['intent_backup_matches'] = True
    report['recovery_receipt_retained'] = (state / 'uid-1000.storage-recovery-attempt').is_file()
    report['result'] = 'existing native lab UID 1000 recovered; encrypted export emitted'
except Exception as error:
    report['error'] = str(error)
finally:
    if guarded:
        try:
            for unit in reversed(UNITS[1:]):
                operation('stop', unit)
            report['clean_shutdown'] = True
        except Exception as error:
            report['shutdown_error'] = str(error)
    report['events'] = {}
    for unit in (UNITS[-1], 'qsee-supplicant.service', 'pocketfed-keymaster-startup.service'):
        report['events'][unit] = subprocess.check_output(
            ['journalctl', '-b', '-u', unit, '-o', 'cat', '--no-pager'], text=True).splitlines()
    emit('native_enroll_finished', report)
