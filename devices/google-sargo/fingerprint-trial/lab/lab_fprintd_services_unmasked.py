#!/usr/bin/python3
"""Retry the packaged chain after fixing its inherited base-image mask."""
import lab_fprintd_services as services
from lab_report import collect

base = services.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-services-unmasked-20260912'
base.DIRECTORY = 'fprintd-services-unmasked'
old_previous = base.previous


def previous(vault):
    records = old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    report = reports['fprintd_interactive_finished']
    assert report['run_id'] == OLD_RUN and report['serial'] == base.original.SERIAL
    assert report['clean_shutdown']
    assert report['steps'][1]['unit'] == 'qsee-supplicant.service'
    assert report['steps'][1]['status'] == 1 and 'LoadState=masked' in report['steps'][1]['state']
    assert not any(s.get('dbus') for s in report['steps'])
    assert not any('rpmb_callback' in line for line in report['events']['qsee-supplicant.service'])
    return records


base.previous = previous
if __name__ == '__main__': base.main()
