#!/usr/bin/python3
"""Touch-driven enrollment/match/nonmatch after the accepted fprintd preflight."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import lab_fprintd_dependencies as dependencies
from lab_report import collect

base = dependencies.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-interactive-20260911'
base.DIRECTORY = 'fprintd-interactive'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    result = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())['fprintd_preflight_finished']
    assert result['run_id'] == OLD_RUN and result['serial'] == base.original.SERIAL
    assert result['result'] == 'fprintd enrollment start/cancel and database reopen passed'
    assert result['enrolled_finger_count'] == 0 and result['credential_unchanged']


def prepare(vault, receiver):
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    code = root / 'overlay/usr/libexec/sargo-fingerprint-lab'
    shutil.copy2(base.HERE / 'fprintd_interactive.py', code)
    controller = code / 'fprintd-preflight.py'
    text = controller.read_text()
    start = text.index("    call(path, iface, 'Claim'")
    end = text.index("    for unit in ('fprintd.service'", start)
    text = text[:start] + """    import fprintd_interactive
    fprintd_interactive.run(bus, path, call, report)
    import hashlib
    metadata = json.loads((Path(__file__).parent / 'authorization.json').read_text())
    assert hashlib.sha256(Path('/var/lib/pocketfed-fpc-auth/uid-1234.credential').read_bytes()).hexdigest() == metadata['credential_sha256']
    report['credential_unchanged'] = True
""" + text[end:]
    text = text.replace('fprintd enrollment start/cancel and database reopen passed', 'fprintd enrollment, matching and nonmatching passed; private database export available')
    text = text.replace("emit('fprintd_preflight_finished', report)", "emit('fprintd_interactive_finished', report)")
    controller.write_text(text)
    manifest = root / 'overlay-manifest.json'; value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['code']['fprintd_interactive.py'] = base.sha(code / 'fprintd_interactive.py')
    value['operation'] = 'One user-guided fingerprint enrollment, match and nonmatch; private export only of new lab fingerprint records'
    manifest.write_bytes(base.original.encoded(value))


def collect_private(vault):
    os.umask(0o077)
    base.original.check_vault(vault)
    base.original.private_file(vault / base.DIRECTORY / 'launch-attempt.json')
    run = vault / base.DIRECTORY / 'runs' / base.RUN
    reports = collect((run / 'uart.log').read_bytes())
    groups = {}
    for name, r in reports.items():
        if not name.startswith('private_fingerprint_'): continue
        path = Path(r['path'])
        assert not path.is_absolute() and all(s not in ('.', '..', '') for s in path.parts)
        assert str(path) == 'qsee-supplicant/pocketfed/fpc-sargo-v1.db' or path.parts[:2] == ('fprint', 'fprintlab')
        assert 0 <= r['sequence'] < r['count'] <= 32 and 0 < r['bytes'] <= 256 * 1024
        key = (str(path), r['sha256'], r['bytes'], r['count'])
        part = base64.b64decode(r['private_data'], validate=True); assert len(part) <= 8192
        parts = groups.setdefault(key, {})
        assert r['sequence'] not in parts or parts[r['sequence']] == part
        parts[r['sequence']] = part
    assert len(groups) <= 9
    output = vault / base.DIRECTORY / 'biometric-records'
    output.mkdir(mode=0o700, exist_ok=True)
    retained = []
    for (relative, digest, size, count), parts in groups.items():
        if set(parts) != set(range(count)): continue
        content = b''.join(parts[i] for i in range(count))
        assert len(content) == size and hashlib.sha256(content).hexdigest() == digest
        path = output / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists(): assert base.original.private_file(path, size) == content
        else: base.original.write_new(path, content)
        retained.append({'path': relative, 'bytes': size, 'sha256': digest})
    expected = reports.get('fingerprint_database_retained', {}).get('files')
    complete = expected is not None and len(retained) == expected
    if complete:
        manifest = output / 'manifest.json'; data = base.original.encoded(retained)
        if manifest.exists(): assert base.original.private_file(manifest) == data
        else: base.original.write_new(manifest, data)
    print(json.dumps({'complete_private_files_retained': len(retained),
        'export_complete': complete,
        'interactive_finished': 'fprintd_interactive_finished' in reports}))


def reserve(vault):
    root, run = base.identity(vault)
    for name, digest in json.loads(base.original.private_file(root / 'launch-seal.json')).items():
        p = (root / name).resolve(); assert p.is_relative_to(root) and base.sha(p) == digest
    assert json.loads(base.original.private_file(root / 'overlay-manifest.json'))['credential_sha256'] == base.sha(vault / 'credential')
    base.original.write_new(root / 'launch-attempt.json', base.original.encoded({
        'serial': base.original.SERIAL, 'run_id': base.RUN, 'no_automatic_retry': True,
        'operation': 'one user-guided fingerprint enrollment, match, nonmatch and private retention of new lab fingerprint records'}))
    return run


base.previous = previous
base.prepare = prepare
base.reserve = reserve
if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == 'collect': collect_private(Path(sys.argv[2]).resolve())
    else: base.main()
