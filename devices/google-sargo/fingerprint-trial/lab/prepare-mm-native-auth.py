#!/usr/bin/python3
"""Check retained lab UID 1000 verification after a six-minute idle period."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import struct
from lab_vault import private_file, write_new, encoded

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUN = 'sargo-fingerprint-lab-mm-native-auth-20260912'
OLD = 'sargo-fingerprint-lab-native-enroll-v2-20260912'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--probe', type=Path, required=True)
args = p.parse_args()
os.umask(0o077)
root = args.root.resolve()
assert root.parent == (REPO / 'out/private').resolve() and root.stat().st_mode & 0o777 == 0o700
source = REPO / 'out/private/sargo-native-enroll-v2-20260912'
prior = json.loads((HERE / 'native-enroll-result-20260912.json').read_text())
assert prior['clean_shutdown'] and prior['prior_lab_credential_unchanged']
assert prior['credential_retained_privately'] and prior['recovery']['usb_host_stopped_after_fastboot']
record = private_file(source / 'credential', 160)
assert struct.unpack('<8sIIII', record[:24]) == (b'FPCAUTH1', 1, 2, 1000, 0x700003e8)
assert record[24:88] == private_file(source / 'intent', 160)[24:88]
overlay = root / 'overlay'
shutil.copytree(source / 'overlay', overlay, symlinks=True)
state = overlay / 'var/lib/pocketfed-fpc-auth'
assert private_file(state / 'uid-1000.intent', 160) == private_file(source / 'intent', 160)
# Restore the completed record in this new disposable overlay. The original
# private intent and all launch/recovery history stay in the preceding vault.
(state / 'uid-1000.intent').unlink()
write_new(state / 'uid-1000.credential', record)
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
shutil.copy2(HERE / 'trial-mm-native-auth.py', code / 'fprintd-preflight.py')
(code / 'authorization.json').write_text(json.dumps({'credential_sha256': hashlib.sha256(record).hexdigest()}) + '\n')
shutil.copy2(args.probe, overlay / 'usr/bin/pocketfed-fpc-auth')
(overlay / 'usr/bin/pocketfed-fpc-auth').chmod(0o755)
units = overlay / 'usr/lib/systemd/system'
oldunit = units / 'pocketfed-fpc-native-enroll-probe.service'
text = oldunit.read_text().replace(OLD, RUN)
text = text.replace('One native UID 1000 credential enrollment on test-sargo',
                    'One retained test-sargo credential verification after idle')
text = text.replace('first-test-sargo-native-uid-1000', '--verify-existing-lab-credential')
assert 'ConditionKernelCommandLine=androidboot.serialno=99NAY1AZG1' in text
assert 'ConditionKernelCommandLine=pocketfed.root_mode=usb' in text
assert 'ConditionKernelCommandLine=pocketfed.liveboot=' + RUN in text
(units / 'pocketfed-fpc-native-auth-probe.service').write_text(text)
oldunit.unlink()
gate = overlay / 'etc/systemd/system/qsee-supplicant.service.d/99-lab-gate.conf'
assert gate.read_text().count(OLD) == 1
gate.write_text(gate.read_text().replace(OLD, RUN))
profile = json.loads(private_file(source / 'profile.json'))
profile['fixture_image'] = 'sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861'
write_new(root / 'profile.json', encoded(profile))
metadata = {'serial': '99NAY1AZG1', 'run_id': RUN, 'linux_uid': 1000,
            'gatekeeper_uid': '0x700003e8', 'enrollment': False, 'idle_seconds': 0,
            'fixture_image': profile['fixture_image'],
            'probe_sha256': hashlib.sha256(args.probe.read_bytes()).hexdigest(),
            'credential_sha256': hashlib.sha256(record).hexdigest(),
            'controller_sha256': hashlib.sha256((code / 'fprintd-preflight.py').read_bytes()).hexdigest(),
            'automatic_retry': False, 'daily_device_access': False}
write_new(root / 'experiment.json', encoded(metadata))
print('Prepared test-sargo existing-credential verification after idle.')
