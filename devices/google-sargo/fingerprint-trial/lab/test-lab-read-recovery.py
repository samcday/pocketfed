#!/usr/bin/python3
"""Synthetic history and second-launch guards; no device operations."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import zlib
import lab_read_recovery as r
import lab_vault as v

os.umask(0o077)
vault = v.REPO / 'out/private' / ('vault-unit-test-recovery-' + secrets.token_hex(8))


def refuses(action):
    try:
        action()
    except (AssertionError, FileNotFoundError, FileExistsError, KeyError):
        return
    raise AssertionError('invalid recovery accepted')


def run_files(root, name):
    run = root / 'runs' / name
    run.mkdir(parents=True)
    (root / 'fixture').mkdir()
    v.write_new(run / 'run.json', v.encoded({'run_id': name, 'device_serial': v.SERIAL,
        'root_mode': 'usb', 'fixture': str(root / 'fixture'), 'kernel_bundle': {'sha256':
        '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'}}))
    for p in (run / 'prepared.json', root / 'fixture/fixture.json', root / 'overlay-manifest.json'):
        v.write_new(p, b'{}')
    return run


def report(run, value):
    raw = json.dumps(value).encode()
    payload = base64.b64encode(zlib.compress(raw)).decode()
    (run / 'uart.log').write_text('SARGO_LAB gatekeeper_finished ' + hashlib.sha256(raw).hexdigest() + ' 0/1 ' + payload + '\n')


try:
    v.initialize(vault)
    first = run_files(vault, v.RUN)
    refuses(lambda: r.previous(vault))
    v.write_new(vault / 'launch-attempt.json', b'{}')
    value = {'serial': v.SERIAL, 'run_id': v.RUN, 'encrypted_credential': None,
        'rpmb_writes': False, 'events': {'enroll': [
            'lab_backend_status=0',
            'lab_enroll_transport=0 secure_status=-30 validated_handle_length=0',
            'lab_enroll_result=-13'], 'rpmb': [
            'event=rpmb_callback cmd=258 detail=34 version_field=0 dispatch=0 reply_status=-1 writes=disabled']}}
    report(first, value)
    r.previous(vault)
    value['serial'] = 'wrong'; report(first, value)
    refuses(lambda: r.previous(vault))
    value['serial'] = v.SERIAL; value['rpmb_writes'] = True; report(first, value)
    refuses(lambda: r.previous(vault))
    value['rpmb_writes'] = False; report(first, value)
    v.write_new(vault / 'credential', bytes(160))
    refuses(lambda: r.previous(vault))
    (vault / 'credential').unlink()  # Synthetic test fixture only.
    root = vault / r.DIRECTORY; root.mkdir(mode=0o700)
    run = run_files(root, r.RUN)
    v.write_new(root / 'prior-result.json', v.encoded(value))
    v.write_new(root / 'prior-launch.json', b'{}')
    v.check_export_runtime = lambda _: None  # No actual EROFS in this unit test.
    r.seal(vault)
    (run / 'prepared.json').write_bytes(b'changed')
    refuses(lambda: r.reserve(vault))
    assert not (root / 'launch-attempt.json').exists()
    (run / 'prepared.json').write_bytes(b'{}')
    assert r.reserve(vault) == run
    refuses(lambda: r.reserve(vault))
    assert (vault / 'launch-attempt.json').read_bytes() == b'{}'
    print('PASS required prior failure, exact serial/result, completed-credential refusal, changed seal refusal, preserved first receipt and one-use recovery launch')
finally:
    if vault.exists():
        assert vault.name.startswith('vault-unit-test-recovery-')
        shutil.rmtree(vault)
