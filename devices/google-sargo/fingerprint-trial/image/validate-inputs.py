#!/usr/bin/python3
"""Require an exact flat set of reviewed RPMs and their SHA-256 manifest."""
import hashlib
from pathlib import Path
import re
import stat
import sys

root = Path(sys.argv[1])
if not stat.S_ISDIR(root.lstat().st_mode):
    raise SystemExit('RPM input root must be a real directory')
manifest = root / 'SHA256SUMS'
if not stat.S_ISREG(manifest.lstat().st_mode):
    raise SystemExit('SHA256SUMS must be a regular file')
expected = {}
for line in manifest.read_text().splitlines():
    match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.+~:-]+\.rpm)', line)
    if not match or match[2] in expected:
        raise SystemExit('Malformed or duplicate RPM manifest entry')
    expected[match[2]] = match[1]
if not expected or {p.name for p in root.iterdir()} != set(expected) | {'SHA256SUMS'}:
    raise SystemExit('RPM directory must contain exactly the listed files and SHA256SUMS')
for name, digest in expected.items():
    path = root / name
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SystemExit('RPM inputs must be regular files: ' + name)
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise SystemExit('RPM digest mismatch: ' + name)
print(f'Verified exact input set: {len(expected)} RPMs')
