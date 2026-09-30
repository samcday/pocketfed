#!/usr/bin/python3
"""Synthetic history/launch guards for the bounded writer; never boots a device."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import zlib
import lab_storage_recovery as r
import lab_vault as v

os.umask(0o077)
vault = v.REPO / 'out/private' / ('vault-unit-test-storage-' + secrets.token_hex(8))


def refuses(action):
    try:
        action()
    except (AssertionError, FileNotFoundError, FileExistsError, KeyError):
        return
    raise AssertionError('invalid storage recovery accepted')


def run_files(root, name):
    run = root / 'runs' / name; run.mkdir(parents=True)
    (root / 'fixture').mkdir()
    v.write_new(run / 'run.json', v.encoded({'run_id': name, 'device_serial': v.SERIAL,
        'root_mode': 'usb', 'fixture': str(root / 'fixture'), 'kernel_bundle': {'sha256':
        '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'}}))
    for p in (run / 'prepared.json', root / 'fixture/fixture.json', root / 'overlay-manifest.json'):
        v.write_new(p, b'{}')
    return run


def report(run, name, value):
    raw = json.dumps(value).encode()
    payload = base64.b64encode(zlib.compress(raw)).decode()
    (run / 'uart.log').write_text('SARGO_LAB ' + name + ' ' + hashlib.sha256(raw).hexdigest() + ' 0/1 ' + payload + '\n')


try:
    v.initialize(vault)
    first = run_files(vault, v.RUN)
    v.write_new(vault / 'launch-attempt.json', b'{}')
    value = {'serial': v.SERIAL, 'run_id': v.RUN, 'encrypted_credential': None,
        'rpmb_writes': False, 'events': {'enroll': ['lab_backend_status=0',
            'lab_enroll_transport=0 secure_status=-30 validated_handle_length=0', 'lab_enroll_result=-13'],
            'rpmb': ['event=rpmb_callback cmd=258 detail=34 version_field=0 dispatch=0 reply_status=-1 writes=disabled']}}
    report(first, 'gatekeeper_finished', value)
    refuses(lambda: r.previous(vault))
    second_root = vault / 'read-path-recovery'; second_root.mkdir(mode=0o700)
    second = run_files(second_root, 'sargo-fingerprint-lab-gatekeeper-rw0-20260911')
    v.write_new(second_root / 'launch-attempt.json', b'{}')
    prior = copy.deepcopy(value); prior['run_id'] = second.name
    report(second, 'gatekeeper_finished', prior)
    r.READ_PROOF_RUN = vault / 'synthetic-read-proof'; r.READ_PROOF_RUN.mkdir()
    # Metadata-only recorded shape copied into a private synthetic UART fixture.
    proof = json.loads((r.HERE / 'storage-frame-probe-result.json').read_text())
    report(r.READ_PROOF_RUN, 'startup_finished', proof)
    r.previous(vault)
    prior['rpmb_writes'] = True; report(second, 'gatekeeper_finished', prior)
    refuses(lambda: r.previous(vault))
    prior['rpmb_writes'] = False; report(second, 'gatekeeper_finished', prior)
    changed = copy.deepcopy(proof); changed['events']['rpmb'] = []
    report(r.READ_PROOF_RUN, 'startup_finished', changed); refuses(lambda: r.previous(vault))
    report(r.READ_PROOF_RUN, 'startup_finished', proof)
    v.write_new(vault / 'credential', bytes(160)); refuses(lambda: r.previous(vault))
    (vault / 'credential').unlink()  # Synthetic fixture only.
    root = vault / r.DIRECTORY; root.mkdir(mode=0o700)
    run = run_files(root, r.RUN)
    for name in ('prior-result.json', 'prior-launch.json', 'prior-recovery-result.json',
                 'prior-recovery-launch.json', 'prior-read-proof.json'):
        v.write_new(root / name, b'{}')
    v.check_export_runtime = lambda _: None  # Synthetic fixture has no EROFS.
    r.seal(vault)
    (root / 'prior-recovery-launch.json').write_bytes(b'changed')
    refuses(lambda: r.reserve(vault)); assert not (root / 'launch-attempt.json').exists()
    (root / 'prior-recovery-launch.json').write_bytes(b'{}')
    assert r.reserve(vault) == run
    refuses(lambda: r.reserve(vault))
    assert (vault / 'launch-attempt.json').read_bytes() == b'{}'
    assert (second_root / 'launch-attempt.json').read_bytes() == b'{}'
    print('PASS both prior failures and read-path proof required, completed credential refusal, sealed history, one-use storage launch and original receipts preserved')
finally:
    if vault.exists():
        assert vault.name.startswith('vault-unit-test-storage-')
        shutil.rmtree(vault)
