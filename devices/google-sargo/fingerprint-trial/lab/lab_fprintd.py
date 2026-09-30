#!/usr/bin/python3
"""Single fprintd start/cancel trial, after successful lab HAT authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import lab_authorization as auth
import lab_vault as original
from lab_report import collect

HERE, REPO = original.HERE, original.REPO
RUN = 'sargo-fingerprint-lab-fprintd-preflight-20260911'
DIRECTORY = 'fprintd-preflight'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def previous(vault):
    auth.previous(vault)
    run = vault / auth.DIRECTORY / 'runs' / auth.RUN
    result = collect((run / 'uart.log').read_bytes())['authorization_finished']
    assert result['result'] == 'retained credential verified after reboot; FPC authorized enrollment; clean service shutdown'
    assert result['serial'] == original.SERIAL and result['run_id'] == auth.RUN
    assert 'lab_fpc_authorize transport=0 outer=0 command=0' in result['events']['authorization']


def receiver(source, output):
    b = json.loads((HERE / 'authorization-build.json').read_text())
    for name, digest in b['receiver_sources']['files'].items(): assert sha(source / name) == digest
    shutil.copytree(source, output)
    h = output / 'lab-writer.h'; text = h.read_text()
    assert text.count(auth.RUN) == 1
    h.write_text(text.replace(auth.RUN, RUN))
    (output / 'sources.json').write_bytes(original.encoded({'run_id': RUN,
        'change': 'Only exact run identity changed; eight write groups and write-error latch retained',
        'base': b['receiver_sources'], 'files': {p.name: sha(p) for p in output.iterdir() if p.name != 'sources.json'}}))


def prepare(vault, binary):
    previous(vault)
    root = vault / DIRECTORY; root.mkdir(mode=0o700); original.sync_directory(vault)
    overlay = root / 'overlay'
    shutil.copytree(vault / auth.DIRECTORY / 'overlay', overlay, symlinks=True)
    code = overlay / 'usr/libexec/sargo-fingerprint-lab'; units = overlay / 'usr/lib/systemd/system'
    shutil.copy2(binary, code / 'rpmb-supplicant-trial')
    shutil.copy2(HERE / 'fprintd-preflight.py', code)
    (code / 'check-authorization').unlink()
    (units / 'pocketfed-fingerprint-lab-authorization.service').unlink()
    startup = units / 'pocketfed-fingerprint-lab-startup.service'
    startup.write_text(startup.read_text().replace('trial-authorization.py', 'fprintd-preflight.py'))
    for name in ('fprintd.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'):
        mask = overlay / 'etc/systemd/system' / name
        if mask.is_symlink():
            assert os.readlink(mask) == '/dev/null'; mask.unlink()
        else: assert not mask.exists()
    native = REPO / 'packages/fpc-auth'
    shutil.copy2(native / 'pocketfed-fpc-auth.socket', units)
    broker = (native / 'pocketfed-fpc-auth.service').read_text()
    broker = broker.replace('qsee-supplicant.service', 'pocketfed-fingerprint-lab-rpmb.service')
    broker = broker.replace('pocketfed-keymaster-startup.service', 'pocketfed-fingerprint-lab-keymaster.service')
    (units / 'pocketfed-fpc-auth.service').write_text(broker)
    drop = overlay / 'etc/systemd/system/fprintd.service.d'; drop.mkdir(parents=True, exist_ok=True)
    deps = 'pocketfed-fingerprint-lab-rpmb.service pocketfed-fingerprint-lab-fpc.service pocketfed-fingerprint-lab-keymaster.service'
    (drop / '99-lab.conf').write_text('[Unit]\nRequires=\nAfter=\nRequires=' + deps + '\nAfter=' + deps + '\nBindsTo=pocketfed-fingerprint-lab-rpmb.service\n[Service]\nRestart=no\nTimeoutStopSec=infinity\nLimitCORE=0\n')
    sysusers = overlay / 'usr/lib/sysusers.d'; sysusers.mkdir(parents=True, exist_ok=True)
    (sysusers / 'pocketfed-fprint-lab.conf').write_text('u fprintlab 1234 "Fingerprint lab" / /usr/sbin/nologin\n')
    state = overlay / 'var/lib/fprint/fpc-qsee'; state.mkdir(mode=0o700, parents=True)
    state.parent.chmod(0o700)
    original.write_new(state / 'initialize-empty', b'')
    original.write_new(root / 'profile.json', original.private_file(vault / 'profile.json'))
    original.write_new(root / 'overlay-manifest.json', original.encoded({
        'serial': original.SERIAL, 'run_id': RUN, 'credential_sha256': sha(vault / 'credential'),
        'receiver_sha256': sha(binary), 'code': {p.name: sha(p) for p in code.iterdir()},
        'units': {p.name: sha(p) for p in units.glob('pocketfed-*.service')},
        'fprintd_dropin_sha256': sha(drop / '99-lab.conf')}))


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
        p = (root / name).resolve(); assert p.is_relative_to(root) and sha(p) == digest
    assert json.loads(original.private_file(root / 'overlay-manifest.json'))['credential_sha256'] == sha(vault / 'credential')
    original.write_new(root / 'launch-attempt.json', original.encoded({'serial': original.SERIAL,
        'run_id': RUN, 'operation': 'one fprintd enrollment start/cancel', 'no_automatic_retry': True}))
    return run


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('receiver', 'prepare', 'seal', 'boot')); p.add_argument('vault', type=Path)
    p.add_argument('--source', type=Path); p.add_argument('--output', type=Path); p.add_argument('--receiver', type=Path)
    a = p.parse_args(); vault = a.vault.resolve()
    if a.action == 'receiver': receiver(a.source, a.output)
    elif a.action == 'prepare': prepare(vault, a.receiver)
    elif a.action == 'seal': seal(vault)
    else:
        run = reserve(vault)
        os.execv('/usr/bin/python3', ['/usr/bin/python3', str(REPO / 'tools/liveboot/run.py'),
            'boot', '--run-dir', str(run), '--uart', original.UART, '--timeout', '240'])
    print('fprintd preflight operation completed: ' + a.action)


if __name__ == '__main__': main()
