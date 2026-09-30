#!/usr/bin/python3
"""Fifty no-touch cycles across ten firmware service lifetimes, one bounded run."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from trial_evidence import Evidence, completed_sequence, run_native

ROOT = Path('/run/sargo-fingerprint-pool-20260913')
CODE = Path(__file__).resolve().parent
GETTY = 'serial-getty@ttyMSM0.service'
VENDOR = 'pocketfed-fpc-pool-vendor-b.service'
FIRMWARE = 'pocketfed-fpc-pool-firmware.service'
LOADERS = ('pocketfed-fpc-pool-supp.service', 'pocketfed-fpc-pool-cmnlib.service',
           'pocketfed-fpc-pool-fpc.service')
MASKS = ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service',
         'pocketfed-keymaster-startup.service', 'pocketfed-fpc-auth.socket',
         'pocketfed-fpc-auth.service')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def unit_state(unit):
    properties = ('LoadState', 'ActiveState', 'SubState', 'Result', 'ExecMainStatus')
    args = ['systemctl', 'show', unit]
    for name in properties:
        args.extend(['-p', name])
    return dict(line.split('=', 1) for line in out(*args).splitlines())


def save(name, value):
    with (ROOT / name).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def masked_services():
    for unit in MASKS:
        assert os.readlink(Path('/etc/systemd/system') / unit) == '/dev/null', unit
    getty = unit_state(GETTY)
    assert getty['LoadState'] == 'masked' and getty['ActiveState'] == 'inactive', getty
    return getty


def exercise_lifetimes(report, evidence):
    for lifetime in range(1, 11):
        report['phase'] = 'loaders'
        evidence.emit('FPC_POOL_LIFETIME_BEGIN', {'lifetime': lifetime})
        for unit in LOADERS:
            assert unit_state(unit)['ActiveState'] == 'inactive', unit
            evidence.emit('FPC_POOL_START', {'lifetime': lifetime, 'unit': unit})
            subprocess.run(['systemctl', 'start', unit], check=True)
            report['started_units'].append(unit)
            evidence.emit('FPC_POOL_STARTED',
                          {'lifetime': lifetime, 'unit': unit, 'state': unit_state(unit)})
        report['phase'] = 'native'
        for number in range((lifetime - 1) * 5 + 1, lifetime * 5 + 1):
            cycle_root = ROOT / ('cycle-%02d' % number)
            cycle_root.mkdir(mode=0o700)
            evidence.emit('FPC_POOL_CYCLE_BEGIN', {'lifetime': lifetime, 'cycle': number})
            native = run_native([str(CODE / 'initialize'), '--cpu=7', '--cycle=' + str(number)],
                                cycle_root, evidence)
            verified = completed_sequence(native)
            result = {'cycle': number, 'lifetime': lifetime,
                      'native_exit_status': native['returncode'], 'sequence_verified': verified}
            save('cycle-%02d-result.json' % number, result)
            evidence.emit('FPC_POOL_CYCLE_RESULT', result)
            assert verified, result
            report['cycles_completed'] += 1
        report['phase'] = 'loader_cleanup'
        save('lifetime-%02d-before-cleanup.json' % lifetime,
             {'lifetime': lifetime, 'cycles_completed': report['cycles_completed']})
        # A stop is requested only after every child has returned and its
        # complete native sequence has been verified and saved.
        for unit in reversed(LOADERS):
            evidence.emit('FPC_POOL_STOP', {'lifetime': lifetime, 'unit': unit})
            stopped = subprocess.run(['systemctl', 'stop', unit])
            state = unit_state(unit)
            evidence.emit('FPC_POOL_STOPPED', {'lifetime': lifetime, 'unit': unit,
                                            'returncode': stopped.returncode, 'state': state})
            assert stopped.returncode == 0 and state['ActiveState'] == 'inactive', state
            report['stopped_units'].append(unit)
        report['lifetimes_completed'] += 1
        evidence.emit('FPC_POOL_LIFETIME_RESULT',
                      {'lifetime': lifetime, 'cycles_completed': report['cycles_completed'],
                       'clean_shutdown': True})


def main():
    os.umask(0o077)
    assert os.geteuid() == 0
    args = Path('/proc/cmdline').read_text().split()
    assert [x for x in args if x.startswith('androidboot.serialno=')] == ['androidboot.serialno=994AY18RSD']
    assert 'pocketfed.root_mode=usb' in args
    assert 'systemd.mask=' + GETTY in args
    runs = [x.split('=', 1)[1] for x in args if x.startswith('pocketfed.liveboot=')]
    assert len(runs) == 1
    assert runs[0] == 'sargo-fingerprint-pool-repeat-05-20260913'
    mode = 'Y'
    assert out('findmnt', '-n', '-o', 'FSTYPE', '/') == 'overlay'
    assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    assert out('getenforce') == 'Enforcing'
    assert b'google,sargo' in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    ROOT.mkdir(mode=0o700)
    evidence = Evidence(ROOT)
    report = {'run': runs[0], 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'serial': '994AY18RSD', 'reuse_invoke_pool': mode, 'started_units': [],
              'stopped_units': [], 'capture_requested': False,
              'credential_operation_requested': False, 'kernel_tracing': False,
              'cpu_affinity': '7', 'planned_cycles': 50, 'planned_lifetimes': 10,
              'cycles_completed': 0, 'lifetimes_completed': 0, 'phase': 'preflight'}
    save('attempt.json', report)
    evidence.emit('FPC_POOL_TRIAL_BEGIN', report)
    started = time.monotonic()
    try:
        assert not evidence.errors, evidence.errors
        manifest = json.loads((CODE / 'manifest.json').read_text())
        for name, key in (('initialize', 'probe_sha256'), ('trial.py', 'controller_sha256'),
                          ('trial_evidence.py', 'evidence_sha256'), ('map-vendor-b.py', 'mapper_sha256')):
            assert hashlib.sha256((CODE / name).read_bytes()).hexdigest() == manifest[key], name
        report['getty'] = masked_services()
        evidence.emit('FPC_POOL_GETTY', report['getty'])
        handoff = json.loads(Path('/run/pocketfed-liveboot/result.json').read_text())
        assert handoff['run_id'] == runs[0] and handoff['result'] == 'pass', handoff
        report['handoff_passed'] = True
        for unit in (VENDOR, FIRMWARE, *LOADERS):
            assert unit_state(unit)['ActiveState'] == 'inactive', unit
        assert not os.path.lexists('/dev/mapper/vendor_b')
        assert not Path('/sys/kernel/tracing/kprobe_events').read_text().strip()
        assert not list(Path('/sys/kernel/tracing/instances').iterdir())
        subprocess.run(['modprobe', 'qseecomtee'], check=True)
        assert Path('/sys/module/qseecomtee/parameters/reuse_invoke_pool').read_text().strip() == mode
        for unit in (VENDOR, FIRMWARE):
            evidence.emit('FPC_POOL_START', {'unit': unit})
            subprocess.run(['systemctl', 'start', unit], check=True)
            evidence.emit('FPC_POOL_STARTED', {'unit': unit, 'state': unit_state(unit)})
        receipt = json.loads(Path('/run/pocketfed-fpc-pool-vendor-b/receipt.json').read_text())
        assert receipt['block_read_only'] is True
        report['vendor_b'] = {key: receipt.get(key) for key in
                              ('observed', 'block_read_only', 'vendor_build', 'lpdump_agrees', 'result')}
        report['getty_before_loaders'] = masked_services()
        assert not evidence.errors, evidence.errors
        exercise_lifetimes(report, evidence)
    except Exception as error:
        report['error'] = repr(error)
        evidence.emit('FPC_POOL_TRIAL_ERROR', {'phase': report['phase'], 'error': repr(error)[:400]})

    # On any failed operation retain the state for inspection. Do not retry or
    # start cleanup of a failed native sequence. No pending call is timeout-killed.
    report['phase_at_end'] = report['phase']
    report['elapsed_seconds'] = time.monotonic() - started
    report['clean_shutdown'] = (report['lifetimes_completed'] == 10)
    report['evidence_errors'] = list(evidence.errors)
    report['passed'] = (report['cycles_completed'] == 50 and report['clean_shutdown']
                        and 'error' not in report and not report['evidence_errors'])
    save('result.json', report)
    evidence.emit('FPC_POOL_TRIAL_SUMMARY', {key: report.get(key) for key in
                  ('run', 'reuse_invoke_pool', 'cycles_completed', 'lifetimes_completed',
                   'clean_shutdown', 'passed', 'elapsed_seconds')})
    evidence.close()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
