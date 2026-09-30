#!/usr/bin/python3
"""Snapshot the frozen receiver with only the lab device-identity replacement."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', required=True, type=Path)
args = p.parse_args()
here = Path(__file__).resolve().parent
parent = here.parent
source = parent / 'rpmb-supplicant.c'
expected = '8216145eb6d509839a8dddd188e8615754322c0af0556657a8b14b1f8355d5f3'
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
old = 'major(st.st_rdev) != 504 || minor(st.st_rdev) != 0'
text = source.read_text()
assert text.count(old) == 1
text = text.replace('#include <unistd.h>', '#include <unistd.h>\n#include "lab-device.h"')
text = text.replace(old, 'lab_rpmb_identity(&st)')
args.output.mkdir(parents=True, exist_ok=False)
for name in ('rpmb-protocol.c', 'rpmb-protocol.h', 'rpmb-mmc.c', 'rpmb-mmc.h',
             'test-rpmb-protocol.c', 'test-rpmb-mmc.c', 'test-rpmb-supplicant.c'):
    shutil.copy2(parent / name, args.output / name)
for name in ('lab-device.h', 'test-lab-device.c'):
    shutil.copy2(here / name, args.output / name)
(args.output / 'rpmb-supplicant.c').write_text(text)
manifest = {'frozen_receiver_sha256': expected,
            'change': 'Replace fixed 504:0 check with named sysfs RPMB/card/device identity; read-only guards unchanged',
            'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(args.output.iterdir())}}
(args.output / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(args.output)
