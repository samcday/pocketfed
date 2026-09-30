#!/usr/bin/python3
"""Prepare the fixed invalid-verification diagnostic, without real credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--helper', required=True, type=Path)
p.add_argument('--receiver', required=True, type=Path)
p.add_argument('--frame-fix', action='store_true', help='prepare the separate payload-length experiment')
args = p.parse_args()
variant = 'storage-frame-probe' if args.frame_fix else 'storage-probe'
assert args.output.name == 'sargo-fingerprint-' + variant + '-20260911'
shutil.copytree(REPO / 'out/liveboot/overlays/sargo-fingerprint-ordered-20260911', args.output, symlinks=True)
code = args.output / 'usr/libexec/sargo-fingerprint-lab'
units = args.output / 'usr/lib/systemd/system'
assert not (args.output / 'var/lib/pocketfed-fpc-auth').exists()
shutil.copy2(args.helper, code / 'storage-probe')
shutil.copy2(args.receiver, code / 'rpmb-supplicant-ro')
for name in ('storage-probe', 'rpmb-supplicant-ro'):
    (code / name).chmod(0o755)
controller = (HERE / 'trial-startup.py').read_text()
controller = controller.replace("'credential_operations': False", "'enrollment': False, 'synthetic_invalid_verification': True")
controller = controller.replace("    operation('restart', 'keymaster')\n", '')
controller = controller.replace("'before_reset ',", "'lab_', 'before_reset ',")
(code / 'trial-startup.py').write_text(controller)
unit = (units / 'pocketfed-fingerprint-lab-keymaster.service').read_text()
unit = unit.replace('Prepare the Sargo Keymaster HMAC agreement', 'Observe storage using one invalid synthetic verification')
for key in ('Requires=', 'After='):
    unit = unit.replace(key, key + 'pocketfed-fingerprint-lab-keymaster.service ', 1)
unit = unit.replace('/usr/libexec/sargo-fingerprint-lab/keymaster-startup --initialize-single-participant',
                    '/usr/libexec/sargo-fingerprint-lab/storage-probe inspect-storage-with-invalid-handle')
(units / 'pocketfed-fingerprint-lab-probe.service').write_text(unit)
profile = json.loads((REPO / 'out/liveboot/profiles/sargo-fingerprint-ordered-20260911.json').read_text())
profile_path = args.output.parent.parent / 'profiles' / (args.output.name + '.json')
profile_path.write_text(json.dumps(profile, indent=2) + '\n')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
manifest = {'run_id': 'sargo-fingerprint-lab-' + variant + '-20260911', 'serial': '99NAY1AZG1',
    'enrollment': False, 'synthetic_invalid_verification': True, 'rpmb_writes': False,
    'code': {p.name: sha(p) for p in code.iterdir()},
    'units': {p.name: sha(p) for p in units.glob('pocketfed-fingerprint-lab-*.service')},
    'sources': {name: sha(HERE / name) for name in ('storage-probe.c', 'test-storage-probe.c',
                'prepare-storage-probe.py', 'boot-storage-probe.py', 'trial-startup.py')},
    'receiver_sources': json.loads(Path('/tmp/sargo-fingerprint-lab-rpmb-' + ('frame' if args.frame_fix else 'trace') + '-source-20260911/sources.json').read_text()),
    'profile': profile, 'status': 'prepared; no boot or verification performed'}
if args.frame_fix:
    for name in ('storage-frame-probe.c', 'test-storage-frame-probe.c', 'boot-storage-frame-probe.py'):
        manifest['sources'][name] = sha(HERE / name)
(HERE / (variant + '-build.json')).write_text(json.dumps(manifest, indent=2) + '\n')
print(args.output)
print(profile_path)
