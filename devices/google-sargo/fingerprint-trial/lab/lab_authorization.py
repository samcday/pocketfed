#!/usr/bin/python3
"""Prepare and run a single post-reboot check using the retained lab credential."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import lab_vault as original
from lab_report import collect

HERE, REPO = original.HERE, original.REPO
RUN = 'sargo-fingerprint-lab-authorization-20260911'
OLD_RUN = 'sargo-fingerprint-lab-gatekeeper-storage-rw-20260911'
DIRECTORY = 'authorization-check'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def previous(vault):
    original.check_vault(vault)
    credential = original.private_file(vault / 'credential', 160)
    original.validate_record(credential, 2, original.private_file(vault / 'intent', 160))
    old = vault / 'authenticated-storage-recovery'
    original.private_file(old / 'launch-attempt.json')
    report = collect((old / 'runs' / OLD_RUN / 'uart.log').read_bytes())['gatekeeper_finished']
    assert report['serial'] == original.SERIAL and report['run_id'] == OLD_RUN
    assert report['result'] == 'credential committed and encrypted export available'
    assert report['events']['enroll'] == ['lab_backend_status=0',
        'lab_enroll_transport=0 secure_status=0 validated_handle_length=58',
        'lab_commit_status=0', 'lab_enroll_result=0']
    return credential


def prepare_receiver(source, output):
    build = json.loads((HERE / 'storage-recovery-build.json').read_text())
    for name, digest in build['receiver_sources']['files'].items():
        assert sha(source / name) == digest
    shutil.copytree(source, output)
    header = output / 'lab-writer.h'
    code = header.read_text()
    assert code.count(OLD_RUN) == 1
    header.write_text(code.replace(OLD_RUN, RUN))
    (output / 'sources.json').write_bytes(original.encoded({
        'run_id': RUN, 'change': 'Exact run token only; same eight-group budget and write-error latch',
        'base': build['receiver_sources'],
        'files': {p.name: sha(p) for p in sorted(output.iterdir()) if p.name != 'sources.json'}}))


def prepare(vault, helper, receiver):
    credential = previous(vault)
    root = vault / DIRECTORY
    root.mkdir(mode=0o700); original.sync_directory(vault)
    overlay = root / 'overlay'
    shutil.copytree(REPO / 'out/liveboot/overlays/sargo-fingerprint-ordered-20260911', overlay, symlinks=True)
    code = overlay / 'usr/libexec/sargo-fingerprint-lab'
    units = overlay / 'usr/lib/systemd/system'
    shutil.copy2(helper, code / 'check-authorization')
    shutil.copy2(receiver, code / 'rpmb-supplicant-trial')
    for name in ('check-authorization', 'rpmb-supplicant-trial'):
        (code / name).chmod(0o755)
    (code / 'rpmb-supplicant-ro').unlink()
    for name in ('trial-authorization.py', 'lab_report.py'):
        shutil.copy2(HERE / name, code / name)
    state = overlay / 'var/lib/pocketfed-fpc-auth'
    state.mkdir(mode=0o700, parents=True)
    original.write_new(state / 'uid-1234.credential', credential)
    original.write_new(code / 'authorization.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'credential_sha256': sha(vault / 'credential')}))
    old_units = vault / 'authenticated-storage-recovery/overlay/usr/lib/systemd/system'
    shutil.copy2(old_units / 'pocketfed-fingerprint-lab-rpmb.service', units)
    unit = (old_units / 'pocketfed-fingerprint-lab-enroll.service').read_text()
    unit = unit.replace('One test-sargo Gatekeeper attempt with host-retained intent', 'Verify retained lab credential and FPC authorization after reboot')
    unit = unit.replace('enroll-once recover-authenticated-storage-test-sargo-uid-1234', 'check-authorization verify-retained-lab-credential')
    unit = unit.replace('DevicePolicy=closed', 'DevicePolicy=closed\nDeviceAllow=/dev/fpc1020 rw')
    unit = unit.replace('# One enrollment attempt only; preserve the intent and both attempt receipts.', '# One verification only; no credential enrollment or biometric database operation.')
    (units / 'pocketfed-fingerprint-lab-authorization.service').write_text(unit)
    startup = units / 'pocketfed-fingerprint-lab-startup.service'
    text = startup.read_text()
    assert text.count('trial-startup.py') == 1
    startup.write_text(text.replace('trial-startup.py', 'trial-authorization.py'))
    original.write_new(root / 'profile.json', original.private_file(vault / 'profile.json'))
    original.write_new(root / 'overlay-manifest.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'credential_sha256': sha(vault / 'credential'),
        'code': {p.name: sha(p) for p in code.iterdir()},
        'units': {p.name: sha(p) for p in units.glob('pocketfed-fingerprint-lab-*.service')}}))


def identity(vault):
    previous(vault)
    root = vault / DIRECTORY; run = root / 'runs' / RUN
    info = json.loads((run / 'run.json').read_text())
    assert info['run_id'] == RUN and info['device_serial'] == original.SERIAL
    assert info['root_mode'] == 'usb' and Path(info['fixture']).resolve() == root / 'fixture'
    assert info['kernel_bundle']['sha256'] == '8cc9eceff25c5c44f648f2af3e1989f7f30a6e53b6388e74ec41f3b0cde4520a'
    return root, run


def seal(vault):
    root, run = identity(vault)
    paths = [run / 'run.json', run / 'prepared.json', root / 'fixture/fixture.json', root / 'overlay-manifest.json']
    original.write_new(root / 'launch-seal.json', original.encoded({str(p.relative_to(root)): sha(p) for p in paths}))


def reserve(vault):
    root, run = identity(vault)
    for name, digest in json.loads(original.private_file(root / 'launch-seal.json')).items():
        p = (root / name).resolve()
        assert p.is_relative_to(root) and sha(p) == digest
    manifest = json.loads(original.private_file(root / 'overlay-manifest.json'))
    assert manifest['credential_sha256'] == sha(vault / 'credential')
    original.write_new(root / 'launch-attempt.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'no_automatic_retry': True,
        'operation': 'one retained-credential verification and FPC HAT authorization; no enrollment'}))
    return run


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('receiver', 'prepare', 'seal', 'boot'))
    p.add_argument('vault', type=Path)
    p.add_argument('--source', type=Path); p.add_argument('--output', type=Path)
    p.add_argument('--helper', type=Path); p.add_argument('--receiver', type=Path)
    a = p.parse_args(); vault = a.vault.resolve()
    if a.action == 'receiver': prepare_receiver(a.source, a.output)
    elif a.action == 'prepare': prepare(vault, a.helper, a.receiver)
    elif a.action == 'seal': seal(vault)
    else:
        run = reserve(vault)
        os.execv('/usr/bin/python3', ['/usr/bin/python3', str(REPO / 'tools/liveboot/run.py'),
            'boot', '--run-dir', str(run), '--uart', original.UART, '--timeout', '240'])
    print('Authorization-check operation completed: ' + a.action)


if __name__ == '__main__': main()
