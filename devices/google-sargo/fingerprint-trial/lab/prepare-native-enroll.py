#!/usr/bin/python3
"""Prepare a private one-shot enrollment fixture for dedicated test-sargo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from lab_vault import write_new, encoded, private_file
from lab_report import collect

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUN = 'sargo-fingerprint-lab-native-enroll-20260912'
IMAGE = 'sha256:39fd4d186f6235332d3ae1c6101b676091243d57d9d7d609a91f8962448f54b1'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--probe', type=Path, required=True)
p.add_argument('--preflight-source', type=Path)
args = p.parse_args()
os.umask(0o077)
root = args.root.resolve()
assert root.parent == (REPO / 'out/private').resolve() and root.stat().st_mode & 0o777 == 0o700
if args.preflight_source:
    previous = args.preflight_source.resolve()
    assert previous == REPO / 'out/private/sargo-native-enroll-20260912'
    reports = collect((previous / 'runs' / RUN / 'uart.log').read_bytes())
    stopped = reports['native_enroll_finished']
    assert stopped['error'] == "[Errno 2] No such file or directory: '/usr/libexec/sargo-fingerprint-lab/encrypt-record'"
    assert stopped['clean_shutdown'] and all(s['action'] == 'stop' for s in stopped['steps'])
    assert not any(stopped['events'].values()) and 'native_enroll_credential' not in reports
    RUN = 'sargo-fingerprint-lab-native-enroll-v2-20260912'
prior = json.loads((HERE / 'native-auth-v2-result-20260912.json').read_text())
assert prior['clean_shutdown'] and prior['credential_unchanged']
assert prior['recovery']['usb_host_stopped_after_fastboot']
assert any('verify_end transport=0 secure_status=0' in s
           for s in prior['events']['pocketfed-fpc-native-auth-probe.service'])
source = REPO / 'out/private/sargo-native-auth-v2-20260912'
overlay = root / 'overlay'
shutil.copytree(source / 'overlay', overlay, symlinks=True)
# Keep this source image's own complete policy and context maps. The restored
# daily candidate already includes the accepted broker policy package.
policy = overlay / 'etc/selinux/targeted'
if policy.exists():
    shutil.rmtree(policy)
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
shutil.copy2(HERE / 'trial-native-enroll.py', code / 'fprintd-preflight.py')
controller = code / 'fprintd-preflight.py'
controller.write_text(controller.read_text().replace('sargo-fingerprint-lab-native-enroll-20260912', RUN))
exporter = REPO / 'out/private/sargo-gatekeeper-20260911/overlay/usr/libexec/sargo-fingerprint-lab/encrypt-record'
export_build = json.loads((HERE / 'gatekeeper-build.json').read_text())
assert hashlib.sha256(exporter.read_bytes()).hexdigest() == export_build['export_helper_sha256']
shutil.copy2(exporter, code / 'encrypt-record')
(code / 'encrypt-record').chmod(0o755)
shutil.copy2(args.probe, overlay / 'usr/bin/pocketfed-fpc-auth')
(overlay / 'usr/bin/pocketfed-fpc-auth').chmod(0o755)
state = overlay / 'var/lib/pocketfed-fpc-auth'
assert sorted(p.name for p in state.iterdir()) == ['uid-1234.credential']
if args.preflight_source:
    intent = private_file(previous / 'intent', 160)
    assert struct.unpack('<8sIIII', intent[:24]) == (b'FPCAUTH1', 1, 1, 1000, 0x700003e8)
    assert intent[88:] == bytes(72)
else:
    intent = struct.pack('<8sIIII', b'FPCAUTH1', 1, 1, 1000, 0x700003e8) + os.urandom(64) + bytes(72)
assert len(intent) == 160
write_new(root / 'intent', intent)
write_new(state / 'uid-1000.intent', intent)
if args.preflight_source:
    key = private_file(previous / 'export-private.pem')
else:
    key = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072'],
                         check=True, capture_output=True).stdout
write_new(root / 'export-private.pem', key)
public = subprocess.check_output(['openssl', 'pkey', '-in', str(root / 'export-private.pem'), '-pubout'])
write_new(root / 'export-public.pem', public)
(code / 'export-public.pem').write_bytes(public)
oldrun = 'sargo-fingerprint-lab-native-auth-v2-20260912'
units = overlay / 'usr/lib/systemd/system'
oldunit = units / 'pocketfed-fpc-native-auth-probe.service'
text = oldunit.read_text().replace(oldrun, RUN)
text = text.replace('One existing native lab credential verification; no enrollment',
                    'One native UID 1000 credential enrollment on test-sargo')
text = text.replace('--verify-existing-lab-credential', 'first-test-sargo-native-uid-1000')
assert 'ConditionKernelCommandLine=androidboot.serialno=99NAY1AZG1' in text
assert 'ConditionKernelCommandLine=pocketfed.root_mode=usb' in text
assert 'ConditionKernelCommandLine=pocketfed.liveboot=' + RUN in text
(units / 'pocketfed-fpc-native-enroll-probe.service').write_text(text)
oldunit.unlink()
gate = overlay / 'etc/systemd/system/qsee-supplicant.service.d/99-lab-gate.conf'
assert gate.read_text().count(oldrun) == 1
gate.write_text(gate.read_text().replace(oldrun, RUN))
profile = json.loads((source / 'profile.json').read_text())
profile['fixture_image'] = IMAGE
write_new(root / 'profile.json', encoded(profile))
metadata = {'serial': '99NAY1AZG1', 'run_id': RUN, 'linux_uid': 1000,
            'gatekeeper_uid': '0x700003e8', 'fixture_image': IMAGE,
            'intent_sha256': hashlib.sha256(intent).hexdigest(),
            'public_key_sha256': hashlib.sha256(public).hexdigest(),
            'probe_sha256': hashlib.sha256(args.probe.read_bytes()).hexdigest(),
            'export_helper_sha256': export_build['export_helper_sha256'],
            'controller_sha256': hashlib.sha256((code / 'fprintd-preflight.py').read_bytes()).hexdigest(),
            'packaged_receiver_sha256': hashlib.sha256((overlay / 'usr/bin/qsee-sargo-rpmb').read_bytes()).hexdigest(),
            'automatic_retry': False, 'daily_device_access': False}
write_new(root / 'experiment.json', encoded(metadata))
write_new(code / 'native-enroll.json', encoded(metadata))
print('Private native-enrollment overlay prepared for test-sargo only.')
