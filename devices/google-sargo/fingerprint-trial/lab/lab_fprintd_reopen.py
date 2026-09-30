#!/usr/bin/python3
"""Reboot and verify the privately retained lab enrollment; never reenroll."""
import json
import os
import shutil
from pathlib import Path
import lab_fprintd_exec as prior
from lab_report import collect

base = prior.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-reopen-20260912'
base.DIRECTORY = 'fprintd-reopen'
old_previous = base.previous


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    result = reports['fprintd_interactive_finished']
    assert result['serial'] == base.original.SERIAL and result['run_id'] == OLD_RUN
    assert result['clean_shutdown'] and result['enrolled_finger_count'] == 1
    assert [r['terminal'] for r in result['interactive']] == ['enroll-completed', 'verify-match', 'verify-unknown-error']
    assert any('Matching fingerprint failed (dispatcher 0, command -211)' in s for s in result['events']['fprintd.service'])
    retained = vault / OLD_DIRECTORY / 'biometric-records'
    records = json.loads(base.original.private_file(retained / 'manifest.json'))
    assert records == result['private_database_export'] and len(records) == 2
    for record in records:
        path = Path(record['path'])
        assert not path.is_absolute() and all(part not in ('', '.', '..') for part in path.parts)
        assert str(path) == 'qsee-supplicant/pocketfed/fpc-sargo-v1.db' or path.parts[:2] == ('fprint', 'fprintlab')
        assert len(base.original.private_file(retained / path, record['bytes'])) == record['bytes']
        assert base.sha(retained / path) == record['sha256']
    return records


def prepare(vault, receiver):
    records = previous(vault)
    source = vault / OLD_DIRECTORY
    old_manifest = json.loads(base.original.private_file(source / 'overlay-manifest.json'))
    old_code = source / 'overlay/usr/libexec/sargo-fingerprint-lab'
    for name, digest in old_manifest['code'].items():
        assert base.sha(old_code / name) == digest
    build = json.loads((base.REPO / 'packages/libfprint/finalization-build.json').read_text())
    assert build['status'] == 'ARM64 build and unit/FPC tests passed'
    library = Path(build['library']['path'])
    assert base.sha(library) == build['library']['sha256']
    root = vault / base.DIRECTORY
    root.mkdir(mode=0o700)
    shutil.copytree(source / 'overlay', root / 'overlay', symlinks=True)
    shutil.copy2(source / 'profile.json', root)
    code = root / 'overlay/usr/libexec/sargo-fingerprint-lab'
    shutil.copy2(receiver, code / 'rpmb-supplicant-trial')
    shutil.copy2(base.HERE / 'fprintd_interactive.py', code)
    shutil.copy2(library, root / 'overlay/usr/lib64/libfprint-2.so.2.0.0')
    (root / 'overlay/var/lib/fprint/fpc-qsee/initialize-empty').unlink()
    for record in records:
        target = root / 'overlay/var/lib' / record['path']
        assert not target.exists()
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        shutil.copy2(source / 'biometric-records' / record['path'], target)
        target.chmod(0o600)
    base.original.write_new(code / 'restored-records.json', base.original.encoded(records))
    controller = code / 'fprintd-preflight.py'
    text = controller.read_text()
    assert text.count(OLD_RUN) == 1
    text = text.replace(OLD_RUN, base.RUN)
    text = text.replace('One device-controlled enrollment/match/nonmatch; no automatic retry.',
                        'One restored match/nonmatch trial; no enrollment and no automatic retry.')
    anchor = "    assert not list(Path('/var/lib/qsee-supplicant').iterdir()), 'initial database namespace is not empty'"
    assert text.count(anchor) == 1
    check = """    import hashlib
    restored = json.loads((Path(__file__).parent / 'restored-records.json').read_text())
    def check_restored():
        for record in restored:
            assert hashlib.sha256((Path('/var/lib') / record['path']).read_bytes()).hexdigest() == record['sha256']
    assert not Path('/var/lib/fprint/fpc-qsee/initialize-empty').exists()
    check_restored()
    report['restored_file_count'] = len(restored)"""
    text = text.replace(anchor, check)
    text = text.replace('fprintd_interactive.run(bus, path, call, report, controls)',
                        "fprintd_interactive.run(bus, path, call, report, controls, verify_only=True)\n    check_restored()\n    report['restored_database_unchanged'] = True")
    text = text.replace('fprintd enrollment, matching and nonmatching passed; private database export available',
                        'restored fingerprint matched and different finger rejected after reboot')
    text = text.replace('All fingerprint checks passed', 'Restored fingerprint checks passed')
    text = text.replace('Enrollment, matching and rejection of a different finger passed.',
                        'Saved fingerprint reopened, matched and rejected a different finger.')
    controller.write_text(text)
    old_manifest.update(run_id=base.RUN, operation='Verify retained enrollment after reboot; no enrollment or database initialization',
        receiver_sha256=base.sha(receiver), libfprint_sha256=base.sha(library),
        libfprint_change='Complete identification state after each successful identification; discard in-memory adaptation',
        code={p.name: base.sha(p) for p in code.iterdir()}, restored_files=records,
        physical_finger='left index; original fprintd metadata label remains right-index-finger')
    base.original.write_new(root / 'overlay-manifest.json', base.original.encoded(old_manifest))


def reserve(vault):
    root, run = base.identity(vault)
    for name, digest in json.loads(base.original.private_file(root / 'launch-seal.json')).items():
        path = (root / name).resolve()
        assert path.is_relative_to(root) and base.sha(path) == digest
    assert json.loads(base.original.private_file(root / 'overlay-manifest.json'))['credential_sha256'] == base.sha(vault / 'credential')
    base.original.write_new(root / 'launch-attempt.json', base.original.encoded({
        'serial': base.original.SERIAL, 'run_id': base.RUN, 'no_automatic_retry': True,
        'operation': 'verify retained fingerprint after reboot; no enrollment, no initialization, no export'}))
    return run


base.previous, base.prepare, base.reserve = previous, prepare, reserve
if __name__ == '__main__': base.main()
