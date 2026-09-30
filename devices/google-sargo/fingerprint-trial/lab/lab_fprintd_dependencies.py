#!/usr/bin/python3
"""Replace the packaged fprintd dependency drop-in with exact lab prerequisites."""
import json
import lab_fprintd_unmasked as unmasked
from lab_report import collect

base = unmasked.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-dependencies-20260911'
base.DIRECTORY = 'fprintd-dependencies'
old_previous, old_prepare = base.previous, base.prepare


def previous(vault):
    old_previous(vault)
    result = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())['fprintd_preflight_finished']
    assert result['run_id'] == OLD_RUN and result['serial'] == base.original.SERIAL
    assert result['error'] == 'service operation failed: fprintd.service'
    assert result['steps'][-1]['diagnostic'] == 'Failed to start fprintd.service: Unit qsee-supplicant.service is masked.\n'
    assert not result['signals'] and not any('dbus' in s for s in result['steps'])
    assert not any('rpmb_callback' in s for s in result['events']['pocketfed-fingerprint-lab-rpmb.service'])


def prepare(vault, receiver):
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    drop = root / 'overlay/etc/systemd/system/fprintd.service.d'
    text = (base.REPO / 'packages/libfprint/90-fpc-qsee.conf').read_text()
    for original, lab in [('qsee-supplicant.service', 'pocketfed-fingerprint-lab-rpmb.service'),
            ('qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-fingerprint-lab-fpc.service'),
            ('pocketfed-keymaster-startup.service', 'pocketfed-fingerprint-lab-keymaster.service')]:
        assert original in text; text = text.replace(original, lab)
    # Same basename in /etc replaces the complete packaged /usr drop-in.
    (drop / '90-fpc-qsee.conf').write_text(text)
    p = drop / '99-lab.conf'
    p.write_text(p.read_text().replace('Requires=\n', '').replace('After=\n', ''))
    controller = root / 'overlay/usr/libexec/sargo-fingerprint-lab/fprintd-preflight.py'
    text = controller.read_text()
    anchor = "    operation('start', 'fprintd.service')"
    assert text.count(anchor) == 1
    text = text.replace(anchor, """    dependencies = subprocess.check_output(['systemctl', 'show', 'fprintd.service', '-p', 'Requires', '--value'], text=True).split()
    report['fprintd_requires'] = dependencies
    assert not {'qsee-supplicant.service', 'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service'}.intersection(dependencies)
    assert {'pocketfed-fingerprint-lab-rpmb.service', 'pocketfed-fingerprint-lab-fpc.service', 'pocketfed-fingerprint-lab-keymaster.service'}.issubset(dependencies)
    operation('start', 'fprintd.service')""")
    controller.write_text(text)
    manifest = root / 'overlay-manifest.json'; value = json.loads(manifest.read_text())
    value['code']['fprintd-preflight.py'] = base.sha(controller)
    value['fprintd_dropins'] = {p.name: base.sha(p) for p in drop.iterdir()}
    value['dependency_change'] = 'Replace packaged 90-fpc-qsee.conf by the same basename under /etc, preserving device permissions; verify effective Requires before fprintd start'
    manifest.write_bytes(base.original.encoded(value))


base.previous = previous
base.prepare = prepare
if __name__ == '__main__': base.main()
