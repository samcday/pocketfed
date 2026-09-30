#!/usr/bin/python3
"""Repeat the untouched-sensor trial with advance human cues before each scan."""
import sys
from pathlib import Path
import lab_fprintd_interactive as interactive
from lab_report import collect

base = interactive.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-countdown-20260911'
base.DIRECTORY = 'fprintd-countdown'
old_previous = base.previous


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    r = reports['fprintd_interactive_finished']
    assert r['run_id'] == OLD_RUN and r['serial'] == base.original.SERIAL
    assert r['error'] == 'interactive result did not match expected phase: enroll'
    assert r['interactive'][0]['terminal'] == 'enroll-unknown-error'
    assert not r['events']['pocketfed-fpc-auth.service']
    assert not any('rpmb_callback' in s for s in r['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


base.previous = previous
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        interactive.collect_private(Path(sys.argv[2]).resolve())
    else:
        base.main()
