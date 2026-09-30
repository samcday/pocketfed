#!/usr/bin/python3
"""Prepare the private, one-attempt Gatekeeper fixture overlay for test-sargo."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from lab_vault import check_vault, private_file, write_new, encoded, REPO, HERE

os.umask(0o077)
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--vault', type=Path, required=True)
p.add_argument('--helper', type=Path, required=True)
p.add_argument('--export-helper', type=Path, required=True)
args = p.parse_args()
vault = args.vault.resolve()
metadata = check_vault(vault)
overlay = vault / 'overlay'
shutil.copytree(REPO / 'out/liveboot/overlays/sargo-fingerprint-ordered-20260911', overlay, symlinks=True)
code = overlay / 'usr/libexec/sargo-fingerprint-lab'
units = overlay / 'usr/lib/systemd/system'
for name in ('trial-gatekeeper.py', 'lab_report.py', 'inspect-device.py', 'guard-device.py'):
    shutil.copy2(HERE / name, code / name)
shutil.copy2(args.helper, code / 'enroll-once')
(code / 'enroll-once').chmod(0o755)
shutil.copy2(args.export_helper, code / 'encrypt-record')
(code / 'encrypt-record').chmod(0o755)
write_new(code / 'export-public.pem', private_file(vault / 'export-public.pem'))
write_new(code / 'enrollment.json', encoded(metadata))
state = overlay / 'var/lib/pocketfed-fpc-auth'
state.mkdir(mode=0o700, parents=True)
write_new(state / 'uid-1234.intent', private_file(vault / 'intent', 160))

controller = units / 'pocketfed-fingerprint-lab-startup.service'
controller.write_text(controller.read_text().replace('trial-startup.py', 'trial-gatekeeper.py'))
enroll = (units / 'pocketfed-fingerprint-lab-keymaster.service').read_text()
enroll = enroll.replace('Prepare the Sargo Keymaster HMAC agreement', 'One test-sargo Gatekeeper attempt with host-retained intent')
enroll = enroll.replace('Requires=pocketfed-fingerprint-lab-fpc.service',
                        'Requires=pocketfed-fingerprint-lab-keymaster.service pocketfed-fingerprint-lab-fpc.service')
enroll = enroll.replace('After=pocketfed-fingerprint-lab-fpc.service',
                        'After=pocketfed-fingerprint-lab-keymaster.service pocketfed-fingerprint-lab-fpc.service')
enroll = enroll.replace('/usr/libexec/sargo-fingerprint-lab/keymaster-startup --initialize-single-participant',
                        '/usr/libexec/sargo-fingerprint-lab/enroll-once first-test-sargo-native-uid-1234')
enroll = enroll.replace('InaccessiblePaths=-/var/lib/pocketfed-fpc-auth ', 'InaccessiblePaths=')
assert 'StateDirectory=' not in enroll
enroll = enroll.replace('UMask=0077', 'UMask=0077\nStateDirectory=pocketfed-fpc-auth\nStateDirectoryMode=0700')
enroll = enroll.replace('# A valid wrapped-key reply makes repeat startup a check, not a new agreement.',
                        '# One enrollment attempt only; preserve the intent and both attempt receipts.')
(units / 'pocketfed-fingerprint-lab-enroll.service').write_text(enroll)
profile = json.loads((REPO / 'out/liveboot/profiles/sargo-fingerprint-ordered-20260911.json').read_text())
write_new(vault / 'profile.json', encoded(profile))
manifest = {'serial': metadata['serial'], 'run_id': metadata['run_id'], 'rpmb_writes': False,
            'intent_sha256': metadata['intent_sha256'],
            'source': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code.iterdir()},
            'units': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in units.glob('pocketfed-fingerprint-lab-*.service')}}
write_new(vault / 'overlay-manifest.json', encoded(manifest))
print('Private overlay prepared; no boot or enrollment performed.')
