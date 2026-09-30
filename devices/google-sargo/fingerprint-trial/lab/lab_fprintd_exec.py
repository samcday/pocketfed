#!/usr/bin/python3
"""Check dedicated broker execution before device-controlled enrollment."""
import json
import shutil
import sys
from pathlib import Path
import lab_fprintd_peer as peer
from lab_report import collect

base = peer.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-exec-20260912'
base.DIRECTORY = 'fprintd-exec'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    reports = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())
    result = reports['fprintd_interactive_finished']
    assert result['serial'] == base.original.SERIAL and result['run_id'] == OLD_RUN
    assert result['clean_shutdown']
    assert any('status=203/EXEC' in s for s in result['events']['pocketfed-fpc-auth.service'])
    assert not any('rpmb_callback' in s for s in result['events']['pocketfed-fingerprint-lab-rpmb.service'])
    assert not any(k.startswith('private_fingerprint_') for k in reports)


def prepare(vault, receiver):
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    code = root / 'overlay/usr/libexec/sargo-fingerprint-lab'
    shutil.copy2(base.HERE / 'broker_readiness.py', code)
    controller = code / 'fprintd-preflight.py'
    text = controller.read_text()
    anchor = "    operation('start', 'pocketfed-fpc-auth.socket')\n"
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + """    operation('start', 'pocketfed-fpc-auth.service')
    from broker_readiness import probe
    report['broker_readiness'] = probe()
    emit('broker_readiness_passed', report['broker_readiness'])
""")
    text = text.replace(".read_text().strip() if pid", ".read_text().rstrip('\\0\\n') if pid")
    controller.write_text(text)
    unit = root / 'overlay/usr/lib/systemd/system/pocketfed-fpc-auth.service'
    text = unit.read_text()
    assert text.count('Type=simple') == 1
    text = text.replace('[Unit]\n', '[Unit]\nStartLimitIntervalSec=infinity\nStartLimitBurst=1\n')
    text = text.replace('Type=simple', 'Type=exec\nRestart=no')
    unit.write_text(text)
    manifest = root / 'overlay-manifest.json'
    value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['code']['broker_readiness.py'] = base.sha(code / 'broker_readiness.py')
    value['units'][unit.name] = base.sha(unit)
    value['broker_readiness'] = 'Start once; verify root and dedicated peer SID; invalid version must return -EPROTO with zero token before Volume Up'
    manifest.write_bytes(base.original.encoded(value))


base.previous, base.prepare = previous, prepare
if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'collect':
        peer.libdir.empty.buttons.interactive.collect_private(Path(sys.argv[2]).resolve())
    else:
        base.main()
