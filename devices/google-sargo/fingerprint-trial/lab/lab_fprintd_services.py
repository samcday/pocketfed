#!/usr/bin/python3
"""Verify saved enrollment with the packaged Sargo listener and service chain."""
import json
import os
import shutil
from pathlib import Path
import lab_fprintd_reopen as reopen
from lab_report import collect

base = reopen.base
OLD_RUN, OLD_DIRECTORY = base.RUN, base.DIRECTORY
base.RUN = 'sargo-fingerprint-lab-fprintd-services-20260912'
base.DIRECTORY = 'fprintd-services'
old_previous, old_prepare = base.previous, base.prepare
UNITS = {'firmware': 'pocketfed-fingerprint-lab-firmware.service',
         'rpmb': 'qsee-supplicant.service',
         'cmnlib': 'qsee-shared-loader@cmnlib64.service',
         'fpc': 'qsee-app-loader@fpctzappfingerprint.service',
         'keymaster': 'pocketfed-keymaster-startup.service'}


def previous(vault):
    records = old_previous(vault)
    report = collect((vault / OLD_DIRECTORY / 'runs' / OLD_RUN / 'uart.log').read_bytes())['fprintd_interactive_finished']
    assert report['serial'] == base.original.SERIAL and report['run_id'] == OLD_RUN
    assert report['clean_shutdown'] and report['restored_database_unchanged'] and report['credential_unchanged']
    assert [r['terminal'] for r in report['interactive']] == ['verify-match', 'verify-no-match']
    assert not any(s.get('dbus', '').startswith('Enroll') for s in report['steps'])
    return records


def prepare(vault, receiver):
    payload = receiver.resolve().parents[2]
    assert receiver.resolve() == payload / 'usr/bin/qsee-sargo-rpmb'
    packaged = json.loads((payload / 'manifest.json').read_text())
    for name, digest in packaged['files'].items():
        path = (payload / name).resolve()
        assert path.is_relative_to(payload) and base.sha(path) == digest
    old_prepare(vault, receiver)
    root = vault / base.DIRECTORY
    overlay = root / 'overlay'
    code = overlay / 'usr/libexec/sargo-fingerprint-lab'
    units = overlay / 'usr/lib/systemd/system'
    etc = overlay / 'etc/systemd/system'
    copied = []

    def copy(relative):
        source, target = payload / relative, overlay / relative
        assert relative in packaged['files']
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in (target.parent, *target.parent.parents):
            if parent == overlay: break
            parent.chmod(0o755)
        shutil.copy2(source, target)
        copied.append(relative)

    for name in ('qsee-supplicant', 'qsee-app-loader', 'qsee-sargo-rpmb',
                 'pocketfed-fpc-auth', 'pocketfed-keymaster-startup'):
        copy('usr/bin/' + name)
    copy('usr/lib64/libfprint-2.so.2.0.0')
    for name in ('qsee-supplicant.service', 'qsee-app-loader@.service', 'qsee-shared-loader@.service',
                 'pocketfed-keymaster-startup.service', 'pocketfed-fpc-auth.service', 'pocketfed-fpc-auth.socket'):
        copy('usr/lib/systemd/system/' + name)
        mask = etc / name
        if mask.is_symlink():
            assert os.readlink(mask) == '/dev/null'
            mask.unlink()

    def drop(unit, name, text):
        directory = etc / (unit + '.d')
        directory.mkdir(mode=0o755, exist_ok=True)
        directory.chmod(0o755)
        (directory / name).write_text(text)
        (directory / name).chmod(0o644)

    # Normal service names, binaries and sandboxing. The operational trial
    # guards disable automatic retries/forced teardown while TAs are attached.
    template = payload / 'usr/share/doc/qsee-supplicant-sargo-rpmb/90-sargo-rpmb.conf'
    drop('qsee-supplicant.service', '90-sargo-rpmb.conf', template.read_text())
    drop('qsee-supplicant.service', '99-lab-gate.conf',
         '[Unit]\nConditionKernelCommandLine=pocketfed.liveboot=' + base.RUN + '\nConditionPathExists=/run/pocketfed-fingerprint-lab/normal-chain-ready\n')
    for unit in ('qsee-app-loader@fpctzappfingerprint.service', 'qsee-shared-loader@cmnlib64.service'):
        drop(unit, '99-lab.conf', '[Unit]\nBindsTo=qsee-supplicant.service\n[Service]\nRestart=no\nTimeoutStartSec=infinity\nTimeoutStopSec=infinity\nLimitCORE=0\n')
    drop('qsee-shared-loader@cmnlib64.service', '90-firmware.conf',
         '[Unit]\nRequires=pocketfed-fingerprint-lab-firmware.service\nAfter=pocketfed-fingerprint-lab-firmware.service\n')
    drop('qsee-app-loader@fpctzappfingerprint.service', '90-common-library.conf',
         (base.REPO / 'devices/google-sargo/fingerprint-trial/qsee-app-loader@fpctzappfingerprint.service.d/90-common-library.conf').read_text())
    drop('pocketfed-fpc-auth.service', '99-lab.conf', '[Unit]\nStartLimitIntervalSec=infinity\nStartLimitBurst=1\n[Service]\nType=exec\nRestart=no\n')
    drop('fprintd.service', '90-fpc-qsee.conf', (payload / 'usr/lib/systemd/system/fprintd.service.d/90-fpc-qsee.conf').read_text())
    drop('fprintd.service', '99-lab.conf', '[Unit]\nBindsTo=qsee-supplicant.service\n[Service]\nRestart=no\nTimeoutStopSec=infinity\nLimitCORE=0\n')
    for name in ('rpmb', 'cmnlib', 'fpc', 'keymaster'):
        (units / ('pocketfed-fingerprint-lab-' + name + '.service')).unlink()
    for name in ('rpmb-supplicant-trial', 'keymaster-startup'):
        (code / name).unlink()
    controller = code / 'fprintd-preflight.py'
    text = controller.read_text()
    # Guard the complete chain while every normal service is still inactive.
    anchor = "    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster'):"
    assert text.count(anchor) == 1
    text = text.replace(anchor, '    unit_names = ' + repr(UNITS) + """
    subprocess.run(['/usr/bin/python3', str(Path(__file__).parent / 'guard-device.py')], check=True)
    # The additive overlay cannot delete a mask inherited from the base image.
    # Unmask only the guarded chain, then check its effective unit load state.
    subprocess.run(['systemctl', 'unmask', 'qsee-supplicant.service',
        'qsee-app-loader@.service', 'qsee-shared-loader@.service',
        'qsee-app-loader@fpctzappfingerprint.service', 'qsee-shared-loader@cmnlib64.service',
        'pocketfed-keymaster-startup.service'], check=True, capture_output=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, capture_output=True)
    for component in ('rpmb', 'cmnlib', 'fpc', 'keymaster'):
        assert subprocess.check_output(['systemctl', 'show', unit_names[component], '-p', 'LoadState', '--value'], text=True).strip() == 'loaded'
    Path('/run/pocketfed-fingerprint-lab/normal-chain-ready').touch(exist_ok=False)
""" + anchor)
    text = text.replace("PREFIX + name + '.service'", 'unit_names[name]')
    text = text.replace("PREFIX + 'rpmb.service'", "'qsee-supplicant.service'")
    start = text.index("    assert not {'qsee-supplicant.service'")
    end = text.index("    operation('start', 'fprintd.service')", start)
    text = text[:start] + "    assert {'qsee-supplicant.service', 'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service'}.issubset(dependencies)\n" + text[end:]
    controller.write_text(text)
    manifest = root / 'overlay-manifest.json'
    value = json.loads(manifest.read_text())
    value.update(code={p.name: base.sha(p) for p in code.iterdir()},
        units={p.name: base.sha(p) for p in units.glob('*.service')},
        normal_runtime_packages=packaged['rpms'],
        packaged_files={p: packaged['files'][p] for p in copied},
        operational_dropins={str(p.relative_to(overlay)): base.sha(p) for p in etc.glob('*.d/*.conf')},
        receiver_sha256=base.sha(receiver), libfprint_sha256=base.sha(overlay / 'usr/lib64/libfprint-2.so.2.0.0'),
        receiver_policy='Packaged named-Sargo identity and process-lifetime write-error latch; no fixed run token or eight-group cap',
        firmware_override='Existing verified lab firmware staging for the dedicated test handset',
        operation='Verify saved enrollment using packaged listener, loader, broker and libfprint; no enrollment')
    manifest.write_bytes(base.original.encoded(value))


base.previous, base.prepare = previous, prepare
if __name__ == '__main__': base.main()
