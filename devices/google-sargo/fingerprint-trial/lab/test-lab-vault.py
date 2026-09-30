#!/usr/bin/python3
"""Exercise real crypto and durable launch guards using disposable synthetic data."""
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import lab_vault as v

os.umask(0o077)
vault = v.REPO / 'out/private' / ('vault-unit-test-' + secrets.token_hex(8))


def refuses(action, errors=(AssertionError, ValueError, FileExistsError)):
    try:
        action()
    except errors:
        return
    raise AssertionError('unsafe input accepted')


try:
    v.initialize(vault)
    intent = v.private_file(vault / 'intent', 160)
    record = bytearray(intent)
    record[12:16] = struct.pack('<I', 2)
    record[88:146] = bytes([0x53]) * 58
    def encrypt(data):
        return subprocess.run(['openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey',
            str(vault / 'export-public.pem'), '-pkeyopt', 'rsa_padding_mode:oaep',
            '-pkeyopt', 'rsa_oaep_md:sha256'], input=data, capture_output=True, check=True).stdout
    cipher = encrypt(record)
    assert v.decrypt(vault, cipher) == record
    refuses(lambda: v.decrypt(vault, cipher[:-1]))
    corrupted = bytearray(cipher); corrupted[100] ^= 1
    refuses(lambda: v.decrypt(vault, corrupted))
    different = bytearray(record); different[24] ^= 1
    refuses(lambda: v.decrypt(vault, encrypt(different)))
    different = bytearray(record); different[16] ^= 1
    refuses(lambda: v.decrypt(vault, encrypt(different)))
    refuses(lambda: v.decrypt(vault, encrypt(intent)))
    (vault / 'intent').chmod(0o644)
    refuses(lambda: v.check_vault(vault))
    (vault / 'intent').chmod(0o600)
    (vault / 'linked-intent').symlink_to('intent')
    refuses(lambda: v.private_file(vault / 'linked-intent'))
    run = vault / 'runs' / v.RUN; run.mkdir(parents=True)
    fixture = vault / 'fixture'; fixture.mkdir()
    metadata = {'run_id': v.RUN, 'device_serial': v.SERIAL, 'root_mode': 'usb',
                'fixture': str(fixture), 'kernel_bundle': {'sha256':
                '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'}}
    for path, data in ((run / 'run.json', v.encoded(metadata)), (run / 'prepared.json', b'{}'),
                       (fixture / 'fixture.json', b'{}'), (vault / 'overlay-manifest.json', b'{}')):
        v.write_new(path, data)
    # Fixture executable presence is checked against the actual exported EROFS
    # at sealing time. This synthetic fixture exercises only seal/launch logic.
    v.check_export_runtime = lambda _: None
    v.seal(vault)
    (run / 'prepared.json').write_bytes(b'{"changed":true}')
    refuses(lambda: v.reserve(vault))
    assert not (vault / 'launch-attempt.json').exists()
    (run / 'prepared.json').write_bytes(b'{}')
    assert v.reserve(vault) == run
    refuses(lambda: v.reserve(vault))
    assert (vault / 'launch-attempt.json').exists()
    print('PASS RSA-OAEP roundtrip, corruption/wrong UID/secret/kind refusal, private permissions, sealed launch integrity and one-use reservation')
finally:
    # This test never boots a device or invokes Gatekeeper. Only synthetic
    # material in this exact randomized test directory is removed.
    if vault.exists():
        assert vault.name.startswith('vault-unit-test-')
        shutil.rmtree(vault)
