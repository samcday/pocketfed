#!/usr/bin/python3
"""Prepare a disposable startup trial with the verified FPC-before-Keymaster order."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--keymaster-helper', type=Path, required=True)
args = p.parse_args()
here = Path(__file__).resolve().parent
repo = here.parents[3]
assert hashlib.sha256(args.keymaster_helper.read_bytes()).hexdigest() == '4cff2ecf8139cbfacb608e378d9fe372b17f105c823742a96cc03fef184cb371'
source = repo / 'out/liveboot/overlays/sargo-fingerprint-readonly-20260911'
shutil.copytree(source, args.output, symlinks=True)
code = args.output / 'usr/libexec/sargo-fingerprint-lab'
units = args.output / 'usr/lib/systemd/system'
for name in ('stage-firmware.py', 'trial-startup.py', 'lab_report.py', 'firmware-manifest.json',
             'inspect-device.py', 'guard-device.py'):
    if name.endswith('.py'):
        ast.parse((here / name).read_text())
    shutil.copy2(here / name, code / name)
shutil.copy2(args.keymaster_helper, code / 'keymaster-startup')
(code / 'keymaster-startup').chmod(0o755)
shutil.copy2(here / 'pocketfed-fingerprint-lab-startup.service', units)

firmware = (here.parent / 'pocketfed-fingerprint-firmware.service').read_text()
firmware = firmware.replace('ExecStart=/usr/bin/python3 /usr/libexec/pocketfed-fingerprint-firmware --ensure',
                            'ExecStart=/usr/bin/python3 /usr/libexec/sargo-fingerprint-lab/stage-firmware.py')
(units / 'pocketfed-fingerprint-lab-firmware.service').write_text(firmware)

keymaster = (repo / 'packages/fpc-auth/pocketfed-keymaster-startup.service').read_text()
keymaster = keymaster.replace('qsee-supplicant.service', 'pocketfed-fingerprint-lab-rpmb.service')
keymaster = keymaster.replace('qsee-shared-loader@cmnlib64.service', 'pocketfed-fingerprint-lab-cmnlib.service')
keymaster = keymaster.replace('qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-fingerprint-lab-fpc.service')
keymaster = keymaster.replace('/usr/bin/pocketfed-keymaster-startup', '/usr/libexec/sargo-fingerprint-lab/keymaster-startup')
(units / 'pocketfed-fingerprint-lab-keymaster.service').write_text(keymaster)

hardening = '''TimeoutStartSec=infinity
TimeoutStopSec=infinity
Restart=no
CapabilityBoundingSet=CAP_SYS_ADMIN
NoNewPrivileges=yes
PrivateDevices=no
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX
RestrictRealtime=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
StandardOutput=journal+console
StandardError=journal+console
'''
for name, dependencies, argument in (
    ('cmnlib', 'pocketfed-fingerprint-lab-firmware.service pocketfed-fingerprint-lab-rpmb.service', '--shared cmnlib64'),
    ('fpc', 'pocketfed-fingerprint-lab-cmnlib.service', 'fpctzappfingerprint')):
    unit = f'''[Unit]
Description=Test-sargo {name} loader
Requires={dependencies}
After={dependencies}
ConditionKernelCommandLine=pocketfed.liveboot

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/qsee-app-loader {argument}
'''+hardening
    (units / ('pocketfed-fingerprint-lab-' + name + '.service')).write_text(unit)
probe = '''[Unit]
Description=Initialize and sleep the test-sargo fingerprint sensor
Requires=pocketfed-fingerprint-lab-fpc.service
After=pocketfed-fingerprint-lab-fpc.service
ConditionKernelCommandLine=pocketfed.liveboot

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/fpc-qsee-probe --initialize
'''+hardening.replace('CapabilityBoundingSet=CAP_SYS_ADMIN', 'CapabilityBoundingSet=')
(units / 'pocketfed-fingerprint-lab-probe.service').write_text(probe)

profile = json.loads((repo / 'tools/liveboot/profiles/google-sargo.json').read_text())
profile['cmdline'] += ['systemd.wants=pocketfed-fingerprint-lab-startup.service', 'systemd.show_status=false']
profile_path = args.output.parent.parent / ('profiles/' + args.output.name + '.json')
assert not profile_path.exists(), 'refusing to replace an existing profile'
profile_path.write_text(json.dumps(profile, indent=2) + '\n')
manifest = {'keymaster_rpm': 'pocketfed-fpc-auth-0.1.0-0.3.pocketfed.fc46.aarch64',
            'keymaster_helper_sha256': hashlib.sha256(args.keymaster_helper.read_bytes()).hexdigest(),
            'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code.iterdir()},
            'units': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in units.glob('pocketfed-fingerprint-lab-*.service')},
            'profile': profile, 'live_status': 'prepared, not booted'}
manifest_path = args.output.parent.parent / ('manifests/' + args.output.name + '.json')
manifest_path.parent.mkdir(exist_ok=True)
assert not manifest_path.exists(), 'refusing to replace existing build evidence'
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
print(args.output)
print(profile_path)
