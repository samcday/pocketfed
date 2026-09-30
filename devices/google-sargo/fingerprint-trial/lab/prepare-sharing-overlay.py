#!/usr/bin/python3
"""Compare the earlier GET-only HMAC diagnostic in a fresh disposable root."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--diagnostic', type=Path, required=True)
args = p.parse_args()
here = Path(__file__).resolve().parent
repo = here.parents[3]
source = repo / 'out/liveboot/overlays/sargo-fingerprint-startup-20260911'
shutil.copytree(source, args.output, symlinks=True)
code = args.output / 'usr/libexec/sargo-fingerprint-lab'
for name in ('inspect-device.py', 'lab_report.py'):
    shutil.copy2(here / name, code / name)
# Keep identical systemd hardening and the read-only receiver. Replace only the
# Keymaster program with the older GET-only diagnostic used on sam-sargo.
shutil.copy2(args.diagnostic, code / 'keymaster-startup')
(code / 'keymaster-startup').chmod(0o755)
controller = (code / 'trial-startup.py').read_text()
old = "    operation('restart', 'keymaster')\n"
assert controller.count(old) == 1
# This old diagnostic deliberately rejects an already-initialized TA. Its
# purpose here is the first startup comparison, not the packaged idempotence test.
(code / 'trial-startup.py').write_text(controller.replace(old, ''))
profile = json.loads((repo / 'out/liveboot/profiles/sargo-fingerprint-startup-20260911.json').read_text())
profile_path = args.output.parent.parent / 'profiles/sargo-fingerprint-sharing-20260911.json'
profile_path.write_text(json.dumps(profile, indent=2) + '\n')
manifest = {'diagnostic_source': 'devices/google-sargo/fingerprint-trial/keymaster-sharing.c',
            'diagnostic_source_sha256': hashlib.sha256((here.parent / 'keymaster-sharing.c').read_bytes()).hexdigest(),
            'code': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code.iterdir()},
            'profile': profile, 'live_status': 'prepared, not booted'}
(here / 'sharing-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(args.output)
print(profile_path)
