#!/usr/bin/python3
"""Deliberate single-use read-path recovery, preserving the first lab attempt."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import lab_vault as original
from lab_report import collect

HERE, REPO = original.HERE, original.REPO
RUN = 'sargo-fingerprint-lab-gatekeeper-rw0-20260911'
DIRECTORY = 'read-path-recovery'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def previous(vault):
    metadata = original.check_vault(vault)
    original.private_file(vault / 'launch-attempt.json')
    assert not (vault / 'credential').exists(), 'completed credential must not be replaced'
    run = original.run_identity(vault)
    result = collect((run / 'uart.log').read_bytes())['gatekeeper_finished']
    assert result['serial'] == original.SERIAL and result['run_id'] == original.RUN
    assert result['encrypted_credential'] is None and not result['rpmb_writes']
    assert result['events']['enroll'] == [
        'lab_backend_status=0',
        'lab_enroll_transport=0 secure_status=-30 validated_handle_length=0',
        'lab_enroll_result=-13']
    callbacks = [s for s in result['events']['rpmb'] if s.startswith('event=rpmb_callback')]
    assert callbacks == ['event=rpmb_callback cmd=258 detail=34 version_field=0 dispatch=0 reply_status=-1 writes=disabled']
    return metadata, result


def prepare(vault, helper, receiver):
    metadata, result = previous(vault)
    build = json.loads((HERE / 'read-recovery-build.json').read_text())
    assert sha(helper) == build['helper_sha256'] and sha(receiver) == build['receiver_sha256']
    for name, digest in build['source_sha256'].items():
        assert sha(HERE / name) == digest
    root = vault / DIRECTORY
    root.mkdir(mode=0o700)
    original.sync_directory(vault)
    original.write_new(root / 'prior-result.json', original.encoded(result))
    original.write_new(root / 'prior-launch.json', original.private_file(vault / 'launch-attempt.json'))
    overlay = root / 'overlay'
    shutil.copytree(vault / 'overlay', overlay, symlinks=True)
    code = overlay / 'usr/libexec/sargo-fingerprint-lab'
    shutil.copy2(helper, code / 'enroll-once')
    shutil.copy2(receiver, code / 'rpmb-supplicant-ro')
    for name in ('enroll-once', 'rpmb-supplicant-ro'):
        (code / name).chmod(0o755)
    controller = (HERE / 'trial-gatekeeper.py').read_text()
    assert controller.count(original.RUN) == 1
    (code / 'trial-gatekeeper.py').write_text(controller.replace(original.RUN, RUN))
    metadata['run_id'] = RUN
    (code / 'enrollment.json').write_bytes(original.encoded(metadata))
    state = overlay / 'var/lib/pocketfed-fpc-auth'
    assert original.private_file(state / 'uid-1234.intent', 160) == original.private_file(vault / 'intent', 160)
    assert not (state / 'uid-1234.credential').exists()
    source = (HERE / 'recover-read-once.c').read_text()
    note = re.search(r'static const char history_note\[\] = ("[^\n]+");', source)
    assert note
    original.write_new(state / 'uid-1234.lab-prior-failure', json.loads(note[1]).encode())
    unit = overlay / 'usr/lib/systemd/system/pocketfed-fingerprint-lab-enroll.service'
    text = unit.read_text()
    assert text.count('first-test-sargo-native-uid-1234') == 1
    unit.write_text(text.replace('first-test-sargo-native-uid-1234', 'recover-read-path-test-sargo-uid-1234'))
    original.write_new(root / 'profile.json', original.private_file(vault / 'profile.json'))
    original.write_new(root / 'overlay-manifest.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'rpmb_writes': False,
        'original_intent_sha256': metadata['intent_sha256'],
        'prior_result_sha256': sha(root / 'prior-result.json'),
        'build_manifest_sha256': sha(HERE / 'read-recovery-build.json'),
        'code': {p.name: sha(p) for p in code.iterdir()},
        'units': {p.name: sha(p) for p in unit.parent.glob('pocketfed-fingerprint-lab-*.service')}}))


def identity(vault):
    previous(vault)
    root = vault / DIRECTORY
    run = root / 'runs' / RUN
    info = json.loads((run / 'run.json').read_text())
    assert info['run_id'] == RUN and info['device_serial'] == original.SERIAL
    assert info['root_mode'] == 'usb' and Path(info['fixture']).resolve() == root / 'fixture'
    assert info['kernel_bundle']['sha256'] == '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'
    return root, run


def seal(vault):
    root, run = identity(vault)
    original.check_export_runtime(root)
    paths = [run / 'run.json', run / 'prepared.json', root / 'fixture/fixture.json',
             root / 'overlay-manifest.json', root / 'prior-result.json', root / 'prior-launch.json']
    original.write_new(root / 'launch-seal.json', original.encoded({
        str(p.relative_to(root)): sha(p) for p in paths}))


def reserve(vault):
    root, run = identity(vault)
    for name, digest in json.loads(original.private_file(root / 'launch-seal.json')).items():
        p = (root / name).resolve()
        assert p.is_relative_to(root) and sha(p) == digest
    original.write_new(root / 'launch-attempt.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'prior_run': original.RUN,
        'reason': 'Deliberate RW version-zero read-path recovery using the original retained secret',
        'rpmb_writes': False, 'no_automatic_retry': True}))
    return run


def collect_result(vault):
    # Do not require credential absence when collecting an already exported record.
    original.check_vault(vault)
    root = vault / DIRECTORY
    original.private_file(root / 'launch-attempt.json')
    run = root / 'runs' / RUN
    reports = collect((run / 'uart.log').read_bytes())
    name = 'gatekeeper_finished' if 'gatekeeper_finished' in reports else 'gatekeeper_credential'
    result = reports[name]
    assert result['run_id'] == RUN and result['serial'] == original.SERIAL
    if result.get('encrypted_credential'):
        record = original.decrypt(vault, base64.b64decode(result['encrypted_credential'], validate=True))
        target = vault / 'credential'
        if target.exists():
            assert original.private_file(target, 160) == record
        else:
            original.write_new(target, record)
    output = run / (name + '.json')
    if not output.exists():
        original.write_new(output, original.encoded(result))
    print(json.dumps({'result': result.get('result'), 'error': result.get('error'),
                      'credential_retained_on_host': (vault / 'credential').exists()}))


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('prepare', 'seal', 'boot', 'collect'))
    p.add_argument('vault', type=Path)
    p.add_argument('--helper', type=Path)
    p.add_argument('--receiver', type=Path)
    args = p.parse_args()
    vault = args.vault.resolve()
    if args.action == 'prepare':
        prepare(vault, args.helper, args.receiver)
    elif args.action == 'seal':
        seal(vault)
    elif args.action == 'collect':
        collect_result(vault)
    else:
        run = reserve(vault)
        os.execv('/usr/bin/python3', ['/usr/bin/python3', str(REPO / 'tools/liveboot/run.py'),
            'boot', '--run-dir', str(run), '--uart', original.UART, '--timeout', '240'])
    print('Read-path recovery operation completed: ' + args.action)


if __name__ == '__main__':
    main()
