#!/usr/bin/python3
"""Repeat the preflight after explicitly removing inherited base-image masks."""
import json
import lab_fprintd as base
from lab_report import collect

OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-unmasked-20260911'
base.DIRECTORY = 'fprintd-unmasked'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    result = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())['fprintd_preflight_finished']
    assert result['run_id'] == OLD_RUN and result['serial'] == base.original.SERIAL
    assert result['error'] == 'service operation failed: pocketfed-fpc-auth.socket'
    assert result['steps'][-1]['unit'] == 'pocketfed-fpc-auth.socket' and result['steps'][-1]['status'] == 1
    assert not result['signals'] and not any('dbus' in s for s in result['steps'])
    assert not any('rpmb_callback' in s for s in result['events']['pocketfed-fingerprint-lab-rpmb.service'])


def prepare(vault, receiver):
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    controller = root / 'overlay/usr/libexec/sargo-fingerprint-lab/fprintd-preflight.py'
    text = controller.read_text()
    assert text.count(OLD_RUN) == 1
    text = text.replace(OLD_RUN, base.RUN)
    anchor = "    operation('start', 'pocketfed-fpc-auth.socket')"
    assert text.count(anchor) == 1
    text = text.replace(anchor, """    # Removing a mask from an additive overlay does not remove the mask in
    # the base OCI. Unmask only these authorized trial services at runtime.
    subprocess.run(['systemctl', 'unmask', 'fprintd.service',
        'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, capture_output=True)
    for unit in ('fprintd.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'):
        assert subprocess.check_output(['systemctl', 'show', unit, '-p', 'LoadState', '--value'], text=True).strip() == 'loaded'
    operation('start', 'pocketfed-fpc-auth.socket')""")
    text = text.replace("'-p', 'SubState', '-p', 'MainPID'", "'-p', 'LoadState', '-p', 'SubState', '-p', 'MainPID'")
    text = text.replace("    report['steps'].append(step)", "    if r.returncode: step['diagnostic'] = r.stderr.decode(errors='replace')\n    report['steps'].append(step)", 1)
    text = text.replace("PREFIX + 'rpmb.service', 'pocketfed-fpc-auth.service'", "PREFIX + 'rpmb.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'")
    controller.write_text(text)
    manifest = root / 'overlay-manifest.json'
    value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['activation_change'] = 'Explicit runtime unmask of fprintd and native broker units after serial/run validation; base masks preserved in original artifacts'
    manifest.write_bytes(base.original.encoded(value))


base.previous = previous
base.prepare = prepare
if __name__ == '__main__': base.main()
