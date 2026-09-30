#!/usr/bin/python3
"""Prepare the generation-03 no-touch disposable probe overlay; access no device here.

Differences from prepare-overlay-02.py: the rebuilt probe and trial-03.py,
new run identifiers, and a mask for serial-getty@ttyMSM0.service so the
getty's TTY hangup cannot sever the controller's console output mid-trial
(the generation-02 failure). The mask is recorded in the overlay policy
inventory. Everything else is unchanged.
"""
import ast
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
WORK = REPO / 'out/fingerprint-kernel-pool-20260913'
OVERLAY = WORK / 'overlay-03'
IMAGE = 'sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
build = json.loads((WORK / 'native-build-03/build.json').read_text())
assert build['returncode'] == 0
shutil.copytree(REPO / 'tools/liveboot/overlay', OVERLAY, symlinks=True)
code = OVERLAY / 'usr/libexec/sargo-fingerprint-pool'
code.mkdir(parents=True)
shutil.copy2(WORK / 'native-build-03/initialize', code / 'initialize')
assert sha(code / 'initialize') == build['probe_sha256']
shutil.copy2(HERE / 'trial-03.py', code / 'trial.py')
shutil.copy2(HERE / 'map-vendor-b.py', code / 'map-vendor-b.py')
for script in ('trial.py', 'map-vendor-b.py'):
    ast.parse((code / script).read_text())
(code / 'initialize').chmod(0o755)
manifest = {'generation': 3, 'probe_sha256': sha(code / 'initialize'),
            'controller_sha256': sha(code / 'trial.py'), 'mapper_sha256': sha(code / 'map-vendor-b.py'),
            'source': {p.name: sha(p) for p in (WORK / 'native-source-03').iterdir()},
            'serial': '994AY18RSD', 'capture_requested': False, 'credential_operation_requested': False,
            'partition_writes': False}
(code / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
units = OVERLAY / 'usr/lib/systemd/system'
units.mkdir(parents=True, exist_ok=True)
names = {'qsee-supplicant.service': 'pocketfed-fpc-pool-supp.service',
         'qsee-shared-loader@.service': 'pocketfed-fpc-pool-cmnlib.service',
         'qsee-app-loader@.service': 'pocketfed-fpc-pool-fpc.service',
         'pocketfed-fingerprint-firmware.service': 'pocketfed-fpc-pool-firmware.service'}
for old, new in names.items():
    text = (WORK / 'image-inspection' / old).read_text().split('[Install]')[0]
    text = text.replace('qsee-supplicant.service', 'pocketfed-fpc-pool-supp.service')
    text = text.replace('Restart=on-failure', 'Restart=no')
    if 'shared-loader' in old:
        text = text.replace('%i', 'cmnlib64')
    elif 'app-loader' in old:
        text = text.replace('%i', 'fpctzappfingerprint')
    elif 'firmware' in old:
        assert text.count('After=blob-wrangler.service\n') == 1
        text = text.replace('After=blob-wrangler.service\n',
                            'After=blob-wrangler.service pocketfed-fpc-pool-vendor-b.service\n'
                            'Requires=pocketfed-fpc-pool-vendor-b.service\n')
    text += '\nTimeoutStopSec=infinity\nStandardOutput=journal+console\nStandardError=journal+console\n'
    (units / new).write_text(text)
(units / 'pocketfed-fpc-pool-vendor-b.service').write_text('''[Unit]
Description=Read-only slot-b vendor mapping for the disposable fingerprint pool trial
Requires=blob-wrangler.service
After=blob-wrangler.service
ConditionKernelCommandLine=pocketfed.liveboot
ConditionKernelCommandLine=androidboot.serialno=994AY18RSD
ConditionKernelCommandLine=pocketfed.root_mode=usb

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/libexec/sargo-fingerprint-pool/map-vendor-b.py
RuntimeDirectory=pocketfed-fpc-pool-vendor-b
RuntimeDirectoryMode=0700
UMask=0077
StandardOutput=journal+console
StandardError=journal+console
''')
maskdir = OVERLAY / 'etc/systemd/system'
for name in (*names, 'qsee-shared-loader@cmnlib64.service', 'qsee-app-loader@fpctzappfingerprint.service',
             'pocketfed-keymaster-startup.service', 'fprintd.service', 'phosh-fingerprint-auth.socket',
             'phosh-fingerprint-auth@.service', 'pocketfed-fpc-auth.service', 'pocketfed-fpc-auth.socket',
             'serial-getty@ttyMSM0.service'):
    target = maskdir / name
    assert not target.exists() and not target.is_symlink(), name
    target.symlink_to('/dev/null')
policy_path = OVERLAY / 'usr/lib/pocketfed-liveboot/policy.json'
policy = json.loads(policy_path.read_text())
assert 'serial-getty@ttyMSM0.service' not in policy['masked_units']
policy['masked_units'].append('serial-getty@ttyMSM0.service')
policy_path.write_text(json.dumps(policy, indent=2) + '\n')
(units / 'pocketfed-fpc-pool-trial.service').write_text('''[Unit]
Description=Disposable Sargo fingerprint allocator comparison
Requires=pocketfed-liveboot-check.service
After=pocketfed-liveboot-check.service
ConditionKernelCommandLine=pocketfed.liveboot
ConditionKernelCommandLine=androidboot.serialno=994AY18RSD
ConditionKernelCommandLine=pocketfed.root_mode=usb

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/libexec/sargo-fingerprint-pool/trial.py
Restart=no
RemainAfterExit=yes
TimeoutStartSec=infinity
TimeoutStopSec=infinity
SendSIGKILL=no
StandardOutput=tty
StandardError=tty
TTYPath=/dev/ttyMSM0
TTYReset=no
TTYVHangup=no
''')
for mode, flag in [('baseline', '0'), ('reuse', '1')]:
    profile = json.loads((REPO / 'tools/liveboot/profiles/google-sargo.json').read_text())
    profile['fixture_image'] = IMAGE
    profile['cmdline'] += ['qseecomtee.reuse_invoke_pool=' + flag,
                           'systemd.wants=pocketfed-fpc-pool-trial.service']
    (WORK / ('profile-' + mode + '-03.json')).write_text(json.dumps(profile, indent=2) + '\n')
(WORK / 'probe-preparation-03.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(OVERLAY)
