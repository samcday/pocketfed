#!/usr/bin/python3
"""Retest device-controlled enrollment with corrected empty-database identify."""
import json
import shutil
import sys
from pathlib import Path
import lab_fprintd_buttons as buttons
from lab_report import collect

base = buttons.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-emptydb-20260912'
base.DIRECTORY = 'fprintd-emptydb'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    r = reports['fprintd_interactive_finished']
    assert r['serial'] == base.original.SERIAL and r['run_id'] == OLD_RUN
    assert r['clean_shutdown'] and not r['events']['pocketfed-fpc-auth.service']
    assert any('Matching fingerprint failed (dispatcher 0, command -208)' in s for s in r['events']['fprintd.service'])
    assert not any('rpmb_callback' in s for s in r['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


def prepare(vault, receiver):
    build = json.loads((base.REPO / 'packages/libfprint/empty-database-build.json').read_text())
    assert build['status'] == 'ARM64 build and unit/FPC tests passed'
    library = Path(build['library']['path'])
    assert base.sha(library) == build['library']['sha256']
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    target = root / 'overlay/usr/lib64/libfprint-2.so.2.0.0'
    target.parent.mkdir(parents=True, exist_ok=True)
    # The private host vault uses umask 077; image system directories must
    # still be searchable by unprivileged services after overlay application.
    target.parent.chmod(0o755)
    shutil.copy2(library, target)
    manifest = root / 'overlay-manifest.json'; value = json.loads(manifest.read_text())
    value['libfprint_sha256'] = base.sha(target)
    value['libfprint_change'] = 'Check actual TA template count before identify; preserve recognized out-of-gallery prints for duplicate detection'
    manifest.write_bytes(base.original.encoded(value))


base.previous, base.prepare = previous, prepare
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        buttons.interactive.collect_private(Path(sys.argv[2]).resolve())
    else: base.main()
