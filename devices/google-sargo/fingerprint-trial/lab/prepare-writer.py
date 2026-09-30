#!/usr/bin/python3
"""Produce a separately named, fixed-run bounded writer from the reviewed receiver."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

here = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
subprocess.run(['/usr/bin/python3', str(here / 'prepare-receiver.py'), '--output', str(args.output)], check=True)
source = args.output / 'rpmb-supplicant.c'
text = source.read_text()
begin = text.index('static int read_only_transfer(')
end = text.index('static int dispatch_rpmb(', begin)
text = text[:begin] + '#include "lab-writer.h"\n\n' + text[end:]
old = 'sargo_rpmb_dispatch(b, SARGO_RPMB_BUFFER, &geometry, false,\n                                read_only_transfer, &rpmb_fd)'
assert text.count(old) == 1
text = text.replace(old, 'sargo_rpmb_dispatch(b, SARGO_RPMB_BUFFER, &geometry, true,\n                                bounded_transfer, &rpmb_fd)')
text = text.replace('--serve-read-only', '--serve-authenticated-lab-trial')
text = text.replace('    umask(0077);', '    if (!writer_identity() || prctl(PR_SET_DUMPABLE, 0)) return 2;\n    writer_authorized = true;\n    umask(0077);')
text = text.replace('read-only RPMB', 'bounded authenticated RPMB').replace('writes=disabled', 'writes=bounded')
text = text.replace('RPMB writes disabled.', 'RPMB writes bound to a fixed lab run and eight signed groups.')
source.write_text(text)
for name in ('lab-writer.h', 'test-lab-writer.c', 'test-writer-supplicant.c'):
    shutil.copy2(here / name, args.output / name)
manifest = {'scope': 'Only fixed test-sargo storage recovery; at most eight authenticated write groups; no key programming or retry after transport/device error',
    'run_id': 'sargo-fingerprint-lab-gatekeeper-storage-rw-20260911',
    'base_receiver': json.loads((args.output / 'sources.json').read_text()),
    'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir()) if p.name != 'sources.json'}}
(args.output / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared bounded writer source only; no device operation')
