#!/usr/bin/python3
"""Retain test-sargo's encrypted native credential export privately."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from lab_report import collect
from lab_vault import private_file, write_new, encoded

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
args = p.parse_args()
os.umask(0o077)
root = args.root.resolve()
assert root.stat().st_mode & 0o777 == 0o700
metadata = json.loads(private_file(root / 'experiment.json'))
assert metadata['serial'] == '99NAY1AZG1'
assert metadata['linux_uid'] == 1000 and metadata['gatekeeper_uid'] == '0x700003e8'
run = root / 'runs' / metadata['run_id']
private_file(run / 'native-enroll-launch.json')
reports = collect((run / 'uart.log').read_bytes())
exported = reports.get('native_enroll_credential')
if exported:
    assert exported['serial'] == metadata['serial'] and exported['run_id'] == metadata['run_id']
    cipher = base64.b64decode(exported['encrypted_credential'], validate=True)
    assert len(cipher) == 384
    private_file(root / 'export-private.pem')
    decoded = subprocess.run(['openssl', 'pkeyutl', '-decrypt', '-inkey', str(root / 'export-private.pem'),
        '-pkeyopt', 'rsa_padding_mode:oaep', '-pkeyopt', 'rsa_oaep_md:sha256'],
        input=cipher, capture_output=True)
    assert decoded.returncode == 0
    record = decoded.stdout
    intent = private_file(root / 'intent', 160)
    assert hashlib.sha256(intent).hexdigest() == metadata['intent_sha256']
    assert len(record) == 160 and struct.unpack('<8sIIII', record[:24]) == (b'FPCAUTH1', 1, 2, 1000, 0x700003e8)
    assert record[24:88] == intent[24:88] and record[146:] == bytes(14) and any(record[89:97])
    if (root / 'credential').exists():
        assert private_file(root / 'credential', 160) == record
    else:
        write_new(root / 'credential', record)
result = reports.get('native_enroll_finished')
if result:
    assert result['serial'] == metadata['serial'] and result['run_id'] == metadata['run_id']
    target = run / 'native-enroll-result.json'
    if target.exists():
        assert json.loads(private_file(target)) == result
    else:
        write_new(target, encoded(result))
print(json.dumps({'verified_report_names': list(reports), 'result': result.get('result') if result else None,
                  'error': result.get('error') if result else None,
                  'credential_retained_privately': (root / 'credential').exists()}))
