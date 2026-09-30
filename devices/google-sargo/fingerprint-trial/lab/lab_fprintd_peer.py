#!/usr/bin/python3
"""Retest enrollment with a dedicated confined authorization-broker peer."""
import json
import shutil
import sys
from pathlib import Path
import lab_fprintd_libdir as libdir
from lab_report import collect

base = libdir.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-peer-20260912'
base.DIRECTORY = 'fprintd-peer'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    r = reports['fprintd_interactive_finished']
    assert r['serial'] == base.original.SERIAL and r['run_id'] == OLD_RUN
    assert r['clean_shutdown'] and not r['events']['pocketfed-fpc-auth.service']
    assert any('authorization broker' in s and 'Permission denied' in s for s in r['events']['fprintd.service'])
    assert r['interactive'][0]['events'][0]['status'] == 'enroll-stage-passed'
    assert not any('rpmb_callback' in s for s in r['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


def prepare(vault, receiver):
    policy_source = base.REPO / 'packages/fpc-selinux/broker'
    build = json.loads((policy_source / 'trial-build.json').read_text())
    assert build['status'] == 'offline compile and boundaries passed; hardware acceptance pending'
    compiled = Path(build['prepared_directory'])
    assert base.sha(compiled / 'policy.35') == build['policy_sha256']
    for name, digest in build['sources'].items():
        assert base.sha(policy_source / name) == digest
    for name, digest in build['context_files'].items():
        assert base.sha(compiled / 'contexts' / name) == digest
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    etc = root / 'overlay/etc'
    policy = etc / 'selinux/targeted/policy'
    contexts = etc / 'selinux/targeted/contexts/files'
    for path in (policy, contexts):
        path.mkdir(parents=True, exist_ok=True)
        # Public system directories must not inherit the host vault's umask.
        for parent in (path, *path.parents):
            if parent == etc:
                break
            parent.chmod(0o755)
    shutil.copy2(compiled / 'policy.35', policy / 'policy.35')
    (policy / 'policy.35').chmod(0o644)
    for name in build['context_files']:
        shutil.copy2(compiled / 'contexts' / name, contexts / name)
        (contexts / name).chmod(0o644)
    controller = root / 'overlay/usr/libexec/sargo-fingerprint-lab/fprintd-preflight.py'
    text = controller.read_text()
    anchor = "    if 'controls' in globals():\n        try:\n"
    assert text.count(anchor) == 1
    text = text.replace(anchor, """    if 'controls' in globals():
        report['process_domains'] = {}
        for unit in ('fprintd.service', 'pocketfed-fpc-auth.service'):
            try:
                pid = int(subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '--value'], text=True))
                report['process_domains'][unit] = Path('/proc/' + str(pid) + '/attr/current').read_text().strip() if pid else 'not running'
            except Exception as error:
                report['process_domains'][unit] = 'metadata unavailable: ' + str(error)
        report['object_labels'] = subprocess.run(['ls', '-ldZ', '/usr/bin/pocketfed-fpc-auth',
            '/run/pocketfed-fpc-auth', '/run/pocketfed-fpc-auth/token.sock', '/var/lib/pocketfed-fpc-auth'],
            text=True, capture_output=True).stdout.splitlines()
        try:
""")
    controller.write_text(text)
    manifest = root / 'overlay-manifest.json'
    value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['broker_policy'] = build
    manifest.write_bytes(base.original.encoded(value))


base.previous, base.prepare = previous, prepare
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        libdir.empty.buttons.interactive.collect_private(Path(sys.argv[2]).resolve())
    else:
        base.main()
