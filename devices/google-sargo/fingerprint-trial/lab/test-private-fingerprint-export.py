#!/usr/bin/python3
"""Synthetic private export recovery; no device or real fingerprint data."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zlib
import lab_fprintd_interactive as trial

os.umask(0o077)
trial.base.original.check_vault = lambda p: None  # Synthetic /tmp fixture only.


def wire(name, value):
    data = json.dumps(value).encode()
    return 'SARGO_LAB ' + name + ' ' + hashlib.sha256(data).hexdigest() + ' 0/1 ' + base64.b64encode(zlib.compress(data)).decode() + '\n'


def record(path, data):
    return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'sequence': 0,
            'count': 1, 'bytes': len(data), 'private_data': base64.b64encode(data).decode()}


def refuses(action):
    try: action()
    except AssertionError: return
    raise AssertionError('invalid private export accepted')


with tempfile.TemporaryDirectory(prefix='fpc-private-export-') as folder:
    vault = Path(folder); root = vault / trial.base.DIRECTORY
    run = root / 'runs' / trial.base.RUN; run.mkdir(parents=True)
    trial.base.original.write_new(root / 'launch-attempt.json', b'{}')
    uart = run / 'uart.log'
    a = record('qsee-supplicant/pocketfed/fpc-sargo-v1.db', b'synthetic opaque database')
    b = record('fprint/fprintlab/fpcqsee/0/7', b'synthetic print metadata')
    uart.write_text(wire('private_fingerprint_a', a))
    trial.collect_private(vault)
    output = root / 'biometric-records'
    assert (output / a['path']).read_bytes() == b'synthetic opaque database'
    assert not (output / 'manifest.json').exists()
    uart.write_text(wire('private_fingerprint_a', a) + wire('private_fingerprint_b', b) +
                   wire('fingerprint_database_retained', {'files': 2, 'private_records': 2}))
    trial.collect_private(vault); trial.collect_private(vault)
    assert len(json.loads((output / 'manifest.json').read_text())) == 2
    for path in ('../outside', '/tmp/outside', 'pocketfed-fpc-auth/uid-1234.credential'):
        changed = dict(a, path=path)
        uart.write_text(wire('private_fingerprint_a', changed))
        refuses(lambda: trial.collect_private(vault))
    changed = dict(a, private_data=base64.b64encode(b'corrupt payload').decode())
    uart.write_text(wire('private_fingerprint_a', changed))
    refuses(lambda: trial.collect_private(vault))
print('PASS partial recovery, completion and repeated collection, private path confinement and corrupted payload refusal')
