#!/usr/bin/python3
"""Reproduce existing-record recovery on test-sargo with the frozen daily binary.

Only the new disposable overlay omits the completed lab UID 1000 handle. The
original vault, intent, completed record, and physical-fingerprint UID 1234 are
retained. The daily-named binary argument/receipt are historical fixed strings;
the controller and unit independently require test serial 99NAY1AZG1 and RUN.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from lab_vault import private_file, write_new, encoded

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUN = 'sargo-fingerprint-lab-native-recovery-20260912'
OLD = 'sargo-fingerprint-lab-native-enroll-v2-20260912'
IMAGE = 'sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861'
BINARY_SHA = 'c36459ccbca8ceb6fed8b745c3817659ae3ebd71af164eff801dde94bbcccb22'
PRIOR = ("One controlled recovery of this trial's unpublished native UID 0x700003e8.\n"
         "Original intent and secret retained. No automatic retry.\n")

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--recovery-binary', type=Path, required=True)
args = p.parse_args()
os.umask(0o077)
root = args.root.resolve()
assert root.parent == (REPO / 'out/private').resolve()
assert root.stat().st_mode & 0o777 == 0o700
assert hashlib.sha256(args.recovery_binary.read_bytes()).hexdigest() == BINARY_SHA
previous = json.loads((HERE / 'mm-native-auth-result-20260912.json').read_text())
assert previous['source_image'] == IMAGE and previous['handoff']['result'] == 'pass'
assert previous['probe']['credential_unchanged'] and previous['probe']['clean_shutdown']
assert previous['recovery']['usb_host_stopped_after_fastboot']
assert any('verify_end transport=0 secure_status=0' in line for line in
           previous['probe']['events']['pocketfed-fpc-native-auth-probe.service'])
source = REPO / 'out/private/sargo-native-enroll-v2-20260912'
intent = private_file(source / 'intent', 160)
record = private_file(source / 'credential', 160)
assert struct.unpack('<8sIIII', intent[:24]) == (b'FPCAUTH1', 1, 1, 1000, 0x700003e8)
assert struct.unpack('<8sIIII', record[:24]) == (b'FPCAUTH1', 1, 2, 1000, 0x700003e8)
assert record[24:88] == intent[24:88] and intent[88:] == bytes(72)
write_new(root / 'intent', intent)
# An additional private copy records the pre-recovery handle. It is never
# supplied to the native enrollment call and may be superseded by that call.
write_new(root / 'prior-credential', record)
overlay = root / 'overlay'
shutil.copytree(source / 'overlay', overlay, symlinks=True)
assert not (overlay / 'etc/selinux/targeted').exists()
state = overlay / 'var/lib/pocketfed-fpc-auth'
assert sorted(p.name for p in state.iterdir()) == ['uid-1000.intent', 'uid-1234.credential']
assert private_file(state / 'uid-1000.intent', 160) == intent
write_new(state / 'uid-1000.first-recovery-attempt', PRIOR.encode())
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
shutil.copy2(HERE / 'trial-native-recovery.py', code / 'fprintd-preflight.py')
shutil.copy2(args.recovery_binary, overlay / 'usr/bin/pocketfed-fpc-auth')
(overlay / 'usr/bin/pocketfed-fpc-auth').chmod(0o755)
key = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                      'rsa_keygen_bits:3072'], check=True, capture_output=True).stdout
write_new(root / 'export-private.pem', key)
public = subprocess.check_output(['openssl', 'pkey', '-in', str(root / 'export-private.pem'), '-pubout'])
write_new(root / 'export-public.pem', public)
(code / 'export-public.pem').write_bytes(public)
export_sha = json.loads((HERE / 'gatekeeper-build.json').read_text())['export_helper_sha256']
assert hashlib.sha256((code / 'encrypt-record').read_bytes()).hexdigest() == export_sha
units = overlay / 'usr/lib/systemd/system'
oldunit = units / 'pocketfed-fpc-native-enroll-probe.service'
unit = oldunit.read_text().replace(OLD, RUN)
unit = unit.replace('One native UID 1000 credential enrollment on test-sargo',
                    'One existing native UID 1000 recovery on test-sargo')
unit = unit.replace('first-test-sargo-native-uid-1000',
                    'recover-storage-sam-sargo-994AY18RSD-uid-1000')
for condition in ('androidboot.serialno=99NAY1AZG1', 'pocketfed.root_mode=usb',
                  'pocketfed.liveboot=' + RUN):
    assert 'ConditionKernelCommandLine=' + condition in unit
assert 'ConditionKernelCommandLine=androidboot.serialno=994AY18RSD' not in unit
(units / 'pocketfed-fpc-native-recovery-probe.service').write_text(unit)
oldunit.unlink()
gate = overlay / 'etc/systemd/system/qsee-supplicant.service.d/99-lab-gate.conf'
assert gate.read_text().count(OLD) == 1
gate.write_text(gate.read_text().replace(OLD, RUN))
profile = json.loads(private_file(source / 'profile.json'))
profile['fixture_image'] = IMAGE
write_new(root / 'profile.json', encoded(profile))
metadata = {
    'serial': '99NAY1AZG1', 'run_id': RUN, 'linux_uid': 1000,
    'gatekeeper_uid': '0x700003e8', 'fixture_image': IMAGE,
    'intent_sha256': hashlib.sha256(intent).hexdigest(),
    'prior_credential_sha256': hashlib.sha256(record).hexdigest(),
    'public_key_sha256': hashlib.sha256(public).hexdigest(),
    'recovery_binary_sha256': BINARY_SHA, 'export_helper_sha256': export_sha,
    'controller_sha256': hashlib.sha256((code / 'fprintd-preflight.py').read_bytes()).hexdigest(),
    'packaged_receiver_sha256': hashlib.sha256((overlay / 'usr/bin/qsee-sargo-rpmb').read_bytes()).hexdigest(),
    'synthetic_prior_receipt': PRIOR, 'existing_native_record_recovery': True,
    'automatic_retry': False, 'daily_device_access': False,
}
write_new(root / 'experiment.json', encoded(metadata))
(code / 'native-enroll.json').write_bytes(encoded(metadata))
print('Prepared existing-record recovery on test-sargo; original private records retained.')
