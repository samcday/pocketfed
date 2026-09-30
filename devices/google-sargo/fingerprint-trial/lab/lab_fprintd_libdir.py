#!/usr/bin/python3
"""Retest corrected identify after restoring system-library directory access."""
import sys
from pathlib import Path
import lab_fprintd_empty as empty
from lab_report import collect

base = empty.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-libdir-20260912'
base.DIRECTORY = 'fprintd-libdir'
old_previous = base.previous


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    r = reports['fprintd_interactive_finished']
    assert r['serial'] == base.original.SERIAL and r['run_id'] == OLD_RUN
    assert r['clean_shutdown'] and not r['events']['pocketfed-fpc-auth.service']
    assert r['error'] == 'service operation failed: fprintd.service'
    assert any('Connection refused' in s for s in r['events']['fprintd.service'])
    assert not any('rpmb_callback' in s for s in r['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


base.previous = previous
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        empty.buttons.interactive.collect_private(Path(sys.argv[2]).resolve())
    else:
        base.main()
