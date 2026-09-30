#!/usr/bin/python3
"""Device-controlled enrollment: physical volume readiness, local instructions."""
import json
import shutil
import sys
from pathlib import Path
import lab_fprintd_interactive as interactive
from lab_report import collect

base = interactive.base
base.RUN = 'sargo-fingerprint-lab-fprintd-buttons-20260912'
base.DIRECTORY = 'fprintd-buttons'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    reports = collect((vault / 'fprintd-countdown/runs/sargo-fingerprint-lab-fprintd-countdown-20260911/uart.log').read_bytes())
    r = reports['fprintd_interactive_finished']
    assert r['serial'] == base.original.SERIAL
    assert r['interactive'][0]['terminal'] == 'enroll-unknown-error'
    assert not r['events']['pocketfed-fpc-auth.service']
    assert not any('rpmb_callback' in s for s in r['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


def prepare(vault, receiver):
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    code = root / 'overlay/usr/libexec/sargo-fingerprint-lab'
    shutil.copy2(base.HERE / 'device_controls.py', code)
    controller = code / 'fprintd-preflight.py'
    text = controller.read_text()
    text = text.replace("    os.write(receipt, b'One enrollment start/cancel; no automatic retry.\\n')",
                        "    os.write(receipt, b'One device-controlled enrollment/match/nonmatch; no automatic retry.\\n')")
    # Bind the display only after run/device validation, before secure startup.
    anchor = "    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster'):"
    assert text.count(anchor) == 1
    text = text.replace(anchor, """    from device_controls import Controls
    controls = Controls(emit)
    controls.screen.show('Starting fingerprint services', 'Please wait. Keep USB connected.')
""" + anchor)
    text = text.replace('    fprintd_interactive.run(bus, path, call, report)',
                        '    fprintd_interactive.run(bus, path, call, report, controls)')
    # Always attempt orderly shutdown after a returned operation, including a
    # user cancellation. Stop at the first failure; do not tear down a listener
    # while a dependent process is still blocked inside secure world.
    start = text.index("    for unit in ('fprintd.service'", text.index("    report['credential_unchanged']"))
    end = text.index("    report['result']", start)
    shutdown = text[start:end]
    text = text[:start] + text[end:]
    anchor = "finally:\n    report['events'] = {}"
    assert text.count(anchor) == 1
    text = text.replace(anchor, """finally:
    if 'controls' in globals():
        try:
""" + ''.join('        ' + line + '\n' for line in shutdown.splitlines()) + """            report['clean_shutdown'] = True
        except Exception as error:
            report['shutdown_error'] = str(error)
        if 'error' in report or 'shutdown_error' in report:
            controls.screen.show('Test stopped', report.get('error', report.get('shutdown_error')),
                'No automatic retry. Codex has the diagnostic result.', 'Keep USB connected.')
        else:
            controls.screen.show('All fingerprint checks passed',
                'Enrollment, matching and rejection of a different finger passed.',
                'Keep USB connected while Codex saves the result.')
        controls.close()
    report['events'] = {}""")
    controller.write_text(text)
    masks = root / 'overlay/etc/systemd/system'
    for name in ('getty@tty1.service', 'autovt@tty1.service'):
        p = masks / name
        if not p.is_symlink(): p.symlink_to('/dev/null')
    manifest = root / 'overlay-manifest.json'; value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['code']['device_controls.py'] = base.sha(code / 'device_controls.py')
    value['readiness'] = 'Physical Volume Up press/release before each phase; no waiting deadline; Volume Down cancels'
    value['display'] = 'VT1 instructions and progress; getty/autovt on VT1 masked only in disposable overlay'
    manifest.write_bytes(base.original.encoded(value))


base.previous, base.prepare = previous, prepare
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        interactive.collect_private(Path(sys.argv[2]).resolve())
    else: base.main()
