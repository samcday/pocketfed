#!/usr/bin/python3
"""Reserve and boot the one fixed invalid-handle storage probe on test-sargo."""
import hashlib
import json
import os
from pathlib import Path
from lab_vault import REPO, UART, write_new, encoded

name = 'sargo-fingerprint-lab-storage-frame-probe-20260911'
run = REPO / 'out/liveboot/runs' / name
metadata = json.loads((run / 'run.json').read_text())
assert metadata['run_id'] == name and metadata['device_serial'] == '99NAY1AZG1'
assert metadata['root_mode'] == 'usb'
assert metadata['kernel_bundle']['sha256'] == '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'
assert Path(metadata['fixture']).resolve() == REPO / 'out/liveboot/fixtures/sargo-fingerprint-storage-frame-probe-20260911'
write_new(run / 'storage-probe-launch.json', encoded({
    'run_id': name, 'serial': '99NAY1AZG1', 'enrollment': False, 'rpmb_writes': False,
    'request': 'one verification with an all-zero synthetic handle and one-byte zero password; no real credential',
    'run_manifest_sha256': hashlib.sha256((run / 'run.json').read_bytes()).hexdigest(),
    'prepared_sha256': hashlib.sha256((run / 'prepared.json').read_bytes()).hexdigest()}))
os.execv('/usr/bin/python3', ['/usr/bin/python3', str(REPO / 'tools/liveboot/run.py'),
    'boot', '--run-dir', str(run), '--uart', UART, '--timeout', '240'])
