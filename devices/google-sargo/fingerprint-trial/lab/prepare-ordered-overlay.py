#!/usr/bin/python3
"""Test FPC residency before Keymaster wraps a message for the fingerprint TA."""
import hashlib
import json
from pathlib import Path
import argparse
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
here = Path(__file__).resolve().parent
repo = here.parents[3]
source = repo / 'out/liveboot/overlays/sargo-fingerprint-startup-20260911'
shutil.copytree(source, args.output, symlinks=True)
code = args.output / 'usr/libexec/sargo-fingerprint-lab'
units = args.output / 'usr/lib/systemd/system'
for name in ('inspect-device.py', 'lab_report.py'):
    shutil.copy2(here / name, code / name)

fpc = units / 'pocketfed-fingerprint-lab-fpc.service'
fpc.write_text(fpc.read_text().replace(' pocketfed-fingerprint-lab-keymaster.service', ''))
km = units / 'pocketfed-fingerprint-lab-keymaster.service'
text = km.read_text()
text = text.replace('Requires=pocketfed-fingerprint-lab-rpmb.service',
                    'Requires=pocketfed-fingerprint-lab-fpc.service pocketfed-fingerprint-lab-rpmb.service')
text = text.replace('After=pocketfed-fingerprint-lab-rpmb.service',
                    'After=pocketfed-fingerprint-lab-fpc.service pocketfed-fingerprint-lab-rpmb.service')
km.write_text(text)
controller = (code / 'trial-startup.py').read_text()
old = '''    for name in ('firmware', 'rpmb', 'cmnlib', 'keymaster', 'fpc', 'probe'):
        operation('start', name)
    for name in ('probe', 'fpc'):
        operation('stop', name)
    # The second helper invocation must find a usable wrapped key and skip HMAC
    # recomputation. This changes no Gatekeeper credential or fingerprint DB.
    operation('restart', 'keymaster')
    for name in ('keymaster', 'cmnlib', 'rpmb'):
        operation('stop', name)
'''
new = '''    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster', 'probe'):
        operation('start', name)
    # Retain the recipient TA while checking the already-ready wrapped-key path.
    operation('restart', 'keymaster')
    for name in ('probe', 'keymaster', 'fpc', 'cmnlib', 'rpmb'):
        operation('stop', name)
'''
assert controller.count(old) == 1
(code / 'trial-startup.py').write_text(controller.replace(old, new))
profile = json.loads((repo / 'out/liveboot/profiles/sargo-fingerprint-startup-20260911.json').read_text())
profile_path = args.output.parent.parent / 'profiles/sargo-fingerprint-ordered-20260911.json'
profile_path.write_text(json.dumps(profile, indent=2) + '\n')
manifest = {'base_run': 'sargo-fingerprint-lab-startup-20260911',
            'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code.iterdir()},
            'units': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in units.glob('pocketfed-fingerprint-lab-*.service')},
            'profile': profile, 'live_status': 'prepared, not booted'}
(here / 'ordered-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(args.output)
print(profile_path)
