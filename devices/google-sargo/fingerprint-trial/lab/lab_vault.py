#!/usr/bin/python3
"""Private host recovery material and one-use launch for the test-sargo trial."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SERIAL = '99NAY1AZG1'
RUN = 'sargo-fingerprint-lab-gatekeeper-ro-20260911'
LINUX_UID = 1234
UART = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_test-sargo-if00-port0'


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def encoded(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def private_file(path, size=None):
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    if size is not None:
        assert info.st_size == size
    return path.read_bytes()


def validate_record(record, kind, intent=None):
    assert len(record) == 160
    assert struct.unpack('<8sIIII', record[:24]) == (b'FPCAUTH1', 1, kind, LINUX_UID, 0x700004d2)
    assert record[146:] == bytes(14) and any(record[24:88])
    if kind == 1:
        assert record[88:146] == bytes(58)
    else:
        assert kind == 2 and any(record[89:97]) and intent is not None
        validate_record(intent, 1)
        assert record[24:88] == intent[24:88], 'returned credential does not match retained intent'


def check_vault(vault):
    info = vault.lstat()
    assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
    assert info.st_uid == os.getuid() and vault.is_relative_to((REPO / 'out/private').resolve())
    assert subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(vault)], text=True).strip() in ('btrfs', 'ext4', 'xfs')
    manifest = json.loads(private_file(vault / 'vault.json'))
    assert manifest['serial'] == SERIAL and manifest['run_id'] == RUN and manifest['linux_uid'] == LINUX_UID
    intent = private_file(vault / 'intent', 160)
    validate_record(intent, 1)
    assert hashlib.sha256(intent).hexdigest() == manifest['intent_sha256']
    private_file(vault / 'export-private.pem')
    assert hashlib.sha256(private_file(vault / 'export-public.pem')).hexdigest() == manifest['public_key_sha256']
    return manifest


def initialize(vault):
    parent = REPO / 'out/private'
    parent.mkdir(mode=0o700, exist_ok=True)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700 and parent.stat().st_uid == os.getuid()
    assert vault.parent == parent.resolve()
    vault.mkdir(mode=0o700)
    sync_directory(parent)
    # No record from either physical phone is copied here.
    intent = struct.pack('<8sIIII', b'FPCAUTH1', 1, 1, LINUX_UID, 0x700004d2) + os.urandom(64) + bytes(72)
    validate_record(intent, 1)
    write_new(vault / 'intent', intent)
    result = subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072'],
                            check=True, capture_output=True)
    write_new(vault / 'export-private.pem', result.stdout)
    result = subprocess.run(['openssl', 'pkey', '-in', str(vault / 'export-private.pem'), '-pubout'],
                            check=True, capture_output=True)
    write_new(vault / 'export-public.pem', result.stdout)
    write_new(vault / 'vault.json', encoded({'serial': SERIAL, 'run_id': RUN, 'linux_uid': LINUX_UID,
        'gatekeeper_uid': '0x700004d2', 'intent_sha256': hashlib.sha256(intent).hexdigest(),
        'public_key_sha256': hashlib.sha256(result.stdout).hexdigest(),
        'storage_mode': 'read-only RPMB; one Gatekeeper attempt; no automatic retry'}))
    check_vault(vault)


def run_identity(vault):
    run = vault / 'runs' / RUN
    metadata = json.loads((run / 'run.json').read_text())
    assert metadata['run_id'] == RUN and metadata['device_serial'] == SERIAL
    assert metadata['root_mode'] == 'usb'
    assert Path(metadata['fixture']).resolve() == vault / 'fixture'
    assert metadata['kernel_bundle']['sha256'] == '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'
    return run


def check_export_runtime(vault):
    for path in ('/usr/libexec/sargo-fingerprint-lab/encrypt-record', '/usr/lib64/libcrypto.so.4'):
        subprocess.run(['dump.erofs', '--path=' + path, str(vault / 'fixture/rootfs.erofs')],
                       check=True, stdout=subprocess.DEVNULL)


def seal(vault):
    check_vault(vault)
    run = run_identity(vault)
    check_export_runtime(vault)
    paths = [run / 'run.json', run / 'prepared.json', vault / 'fixture/fixture.json', vault / 'overlay-manifest.json']
    write_new(vault / 'launch-seal.json', encoded({str(p.relative_to(vault)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))


def reserve(vault):
    check_vault(vault)
    run = run_identity(vault)
    hashes = json.loads(private_file(vault / 'launch-seal.json'))
    for relative, digest in hashes.items():
        path = (vault / relative).resolve()
        assert path.is_relative_to(vault)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    write_new(vault / 'launch-attempt.json', encoded({'serial': SERIAL, 'run_id': RUN,
        'outcome': 'reserved before boot; completion may be unknown; never automatically repeat'}))
    return run


def decrypt(vault, ciphertext):
    assert len(ciphertext) == 384
    result = subprocess.run(['openssl', 'pkeyutl', '-decrypt', '-inkey', str(vault / 'export-private.pem'),
        '-pkeyopt', 'rsa_padding_mode:oaep', '-pkeyopt', 'rsa_oaep_md:sha256'],
        input=ciphertext, capture_output=True)
    if result.returncode:
        raise ValueError('encrypted result did not decrypt')
    validate_record(result.stdout, 2, private_file(vault / 'intent', 160))
    return result.stdout


def collect_result(vault):
    from lab_report import collect
    check_vault(vault)
    private_file(vault / 'launch-attempt.json')
    run = run_identity(vault)
    reports = collect((run / 'uart.log').read_bytes())
    name = 'gatekeeper_finished' if 'gatekeeper_finished' in reports else 'gatekeeper_credential'
    result = reports[name]
    assert result['run_id'] == RUN and result['serial'] == SERIAL
    ciphertext = result.get('encrypted_credential')
    if ciphertext:
        record = decrypt(vault, base64.b64decode(ciphertext, validate=True))
        target = vault / 'credential'
        if target.exists():
            assert private_file(target, 160) == record
        else:
            write_new(target, record)
    output = run / (name + '.json')
    if not output.exists():
        write_new(output, encoded(result))
    print(json.dumps({'result': result.get('result'), 'error': result.get('error'),
                      'credential_retained_on_host': (vault / 'credential').exists()}))


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('init', 'seal', 'boot', 'collect'))
    p.add_argument('vault', type=Path)
    args = p.parse_args()
    vault = args.vault.resolve()
    if args.action == 'init':
        initialize(vault)
    elif args.action == 'seal':
        seal(vault)
    elif args.action == 'collect':
        collect_result(vault)
    else:
        run = reserve(vault)
        os.execv('/usr/bin/python3', ['/usr/bin/python3', str(REPO / 'tools/liveboot/run.py'), 'boot',
            '--run-dir', str(run), '--uart', UART, '--timeout', '240'])
    print('Private lab vault operation completed: ' + args.action)


if __name__ == '__main__':
    main()
