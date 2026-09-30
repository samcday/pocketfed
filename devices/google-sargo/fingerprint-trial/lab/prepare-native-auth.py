#!/usr/bin/python3
"""Prepare the next disposable native-verification experiment on test-sargo."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
RUN = 'sargo-fingerprint-lab-native-auth-v2-20260912'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--probe', type=Path, required=True)
args = p.parse_args()
os.umask(0o077)
assert hashlib.sha256(args.probe.read_bytes()).hexdigest() == '86d2d04afa1286275106f5e0751b4ba3270b0cb69cd1df17081107541b12da35'
prior = json.loads((HERE / 'fprintd-services-unmasked-result.json').read_text())
assert prior['clean_shutdown'] and prior['credential_unchanged'] and prior['restored_database_unchanged']
assert [i['terminal'] for i in prior['interactive']] == ['verify-match', 'verify-no-match']
source = REPO / 'out/private/sargo-gatekeeper-20260911/fprintd-services-unmasked'
overlay = args.root / 'overlay'
shutil.copytree(source / 'overlay', overlay, symlinks=True)
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
shutil.copy2(HERE / 'trial-native-auth.py', code / 'fprintd-preflight.py')
shutil.copy2(HERE / 'inspect-device.py', code / 'inspect-device.py')
# The normal broker path has the exact tested executable SELinux context.
# Its ordinary socket and service remain masked in this disposable experiment.
shutil.copy2(args.probe, overlay / 'usr/bin/pocketfed-fpc-auth')
(overlay / 'usr/bin/pocketfed-fpc-auth').chmod(0o755)
etc = overlay / 'etc/systemd/system'
for name in ('fprintd.service', 'pocketfed-fpc-auth.service',
             'pocketfed-fpc-auth.socket', 'phosh-fingerprint-auth.socket'):
    target = etc / name
    if target.is_symlink():
        assert os.readlink(target) == '/dev/null'
    else:
        assert not target.exists()
        target.symlink_to('/dev/null')
gate = etc / 'qsee-supplicant.service.d/99-lab-gate.conf'
text = gate.read_text()
old = 'sargo-fingerprint-lab-fprintd-services-unmasked-20260912'
assert text.count(old) == 1
gate.write_text(text.replace(old, RUN))
unit = (REPO / 'devices/google-sargo/fingerprint-trial/daily' /
        'recovery-launch-manifest.json')
frozen = Path('/tmp/sargo-fingerprint-daily-upgrade-20260912/recovery-bundle')
manifest = json.loads(unit.read_text())
name = 'pocketfed-fpc-storage-recovery-once.service'
assert hashlib.sha256((frozen / name).read_bytes()).hexdigest() == manifest['files'][name]
text = (frozen / name).read_text()
text = text.replace('Description=One authorized storage recovery for sam-sargo UID 1000',
                    'Description=One existing native lab credential verification; no enrollment')
text = text.replace('ConditionKernelCommandLine=androidboot.serialno=994AY18RSD',
                    'ConditionKernelCommandLine=androidboot.serialno=99NAY1AZG1\nConditionKernelCommandLine=pocketfed.root_mode=usb\nConditionKernelCommandLine=pocketfed.liveboot=' + RUN)
text = text.replace('ExecStart=/run/sargo-fingerprint-storage-recovery/recover-storage-once recover-storage-sam-sargo-994AY18RSD-uid-1000',
                    'ExecStart=/usr/bin/pocketfed-fpc-auth --verify-existing-lab-credential')
text = text.replace('StandardOutput=journal\n', 'StandardOutput=journal+console\n')
text = text.replace('StandardError=journal\n', 'StandardError=journal+console\n')
assert 'recover-storage-' not in text and '994AY18RSD' not in text
(overlay / 'usr/lib/systemd/system/pocketfed-fpc-native-auth-probe.service').write_text(text)
profile = json.loads((source / 'profile.json').read_text())
fixture_image = json.loads((source / 'fixture/fixture.json').read_text())['inputs']['image']['id']
profile['fixture_image'] = fixture_image
(args.root / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
evidence = {'run_id': RUN, 'serial': '99NAY1AZG1', 'operation': 'verify existing native lab credential once',
            'enrollment': False, 'credential_export': False, 'linux_uid': 1234,
            'source_overlay': str(source / 'overlay'),
            'fixture_image': fixture_image,
            'probe_sha256': hashlib.sha256(args.probe.read_bytes()).hexdigest(),
            'controller_sha256': hashlib.sha256((code / 'fprintd-preflight.py').read_bytes()).hexdigest(),
            'packaged_receiver_sha256': hashlib.sha256((overlay / 'usr/bin/qsee-sargo-rpmb').read_bytes()).hexdigest()}
(args.root / 'experiment.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence, indent=2))
