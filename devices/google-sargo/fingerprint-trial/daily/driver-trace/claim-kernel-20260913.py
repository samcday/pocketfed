#!/usr/bin/python3
"""Trace one real fprintd Claim/Release in a temporary copy of its service.

The production service and Phosh socket stay masked. The copied service retains
the packaged sandbox and device access, with only a traced-library bind and UART
output added. No enrollment, verification, deletion or native recovery is called.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/var/tmp/sargo-fingerprint-claim-kernel-20260913')
CPU_ROOT = Path('/var/tmp/sargo-fingerprint-cpu-compare-20260913')
sys.path.insert(0, str(CPU_ROOT))
import controller as c

DAEMON = 'pocketfed-fpc-claim-daemon-20260913.service'
TRIAL = 'pocketfed-fpc-claim-kernel-20260913.service'
LIB = Path('/usr/local/lib64/pocketfed-fingerprint-trace-20260912/libfprint-2.so.2.0.0')
LIB_SHA = '274ac3814562947589a31fc90e03e6c7d0974eee8bbb3b19cdbc58ff7fb8d937'
CLIENT = Path('/usr/local/libexec/pocketfed-fpc-claim-only-20260912')
CLIENT_SHA = '55a4f37ea5cba8b26eebe4830f13c9f8a5891133d665a694ac7fd26b1dfa2419'
FRAGMENTS = ('/usr/lib/systemd/system/fprintd.service',
             '/usr/lib/systemd/system/fprintd.service.d/90-fpc-qsee.conf',
             '/etc/systemd/system/fprintd.service.d/99-fingerprint-lifetime.conf')


def guard():
    c.guard()
    assert ROOT.resolve() == ROOT and ROOT.stat().st_uid == 0
    assert ROOT.stat().st_mode & 0o777 == 0o700
    assert c.sha(LIB) == LIB_SHA and c.sha(CLIENT) == CLIENT_SHA
    assert Path(__file__).resolve().parent == ROOT
    for cpu in (7, 1):
        previous = json.loads((CPU_ROOT / f'cpu{cpu}/result.json').read_text())
        assert previous['passed'] and previous['boot_id'] == c.BOOT
    # Settings has no reason to share this deliberately isolated DBus lifetime.
    assert subprocess.run(['pgrep', '-f', '^/usr/bin/gnome-control-center'],
                          stdout=subprocess.DEVNULL).returncode == 1


def stage():
    guard()
    units = Path('/run/systemd/system')
    assert not os.path.lexists(units / DAEMON) and not os.path.lexists(units / TRIAL)
    assert c.sha(Path(FRAGMENTS[1])) == 'c7a475b77dd740730b825259bc6731664d27a91f6b1c7b08e697b44340946c37'
    assert c.sha(Path(FRAGMENTS[2])) == 'b0e2ad5a73d04139724b4af90a173813b6893d2f478755c9d88d39bf2654d882'
    contents = {p: Path(p).read_text() for p in FRAGMENTS}
    c.save(ROOT / 'stage-attempt.json', {'serial': c.SERIAL, 'boot_id': c.BOOT,
                                       'fragments': contents})
    with (units / DAEMON).open('x') as stream:
        stream.write('\n'.join(contents.values()))
        stream.write(f'''\n[Unit]
ConditionKernelCommandLine=androidboot.serialno={c.SERIAL}
[Service]
BindReadOnlyPaths={LIB}:/usr/lib64/libfprint-2.so.2.0.0
StandardOutput=append:/dev/ttyMSM0
StandardError=append:/dev/ttyMSM0
TimeoutStartSec=infinity
''')
    with (units / TRIAL).open('x') as stream:
        stream.write(f'''[Unit]
Description=One daily fprintd Claim with scoped kernel tracing
ConditionKernelCommandLine=androidboot.serialno={c.SERIAL}
[Service]
Type=exec
ExecStart=/usr/bin/python3 -u {Path(__file__).resolve()} --claim
Restart=no
TimeoutStartSec=infinity
TimeoutStopSec=infinity
LimitCORE=0
UMask=0077
StandardInput=null
StandardOutput=append:/dev/ttyMSM0
StandardError=append:/dev/ttyMSM0
''')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    record = {'serial': c.SERIAL, 'boot_id': c.BOOT,
              'script_sha256': c.sha(Path(__file__)),
              'unit_sha256': {name: c.sha(units / name) for name in (DAEMON, TRIAL)},
              'source_sha256': {p: c.sha(Path(p)) for p in FRAGMENTS},
              'sensor_opened': False}
    c.save(ROOT / 'staged.json', record)
    print('Temporary fprintd service and trace controller staged; both inactive.')


def claim():
    guard()
    staged = json.loads((ROOT / 'staged.json').read_text())
    assert staged['boot_id'] == c.BOOT and staged['script_sha256'] == c.sha(Path(__file__))
    for name, digest in staged['unit_sha256'].items():
        assert c.sha(Path('/run/systemd/system') / name) == digest
    for path, digest in staged['source_sha256'].items():
        assert c.sha(Path(path)) == digest
    assert c.output(['systemctl', 'show', DAEMON, '-p', 'ActiveState', '--value']) == 'inactive'
    report = {'serial': c.SERIAL, 'boot_id': c.BOOT, 'kernel': c.RELEASE,
              'started_at': time.time(), 'capture_started': False,
              'credential_operations': False, 'automatic_retry': False,
              'operations': ['GetDefaultDevice', 'ListEnrolledFingers', 'Claim', 'Release'],
              'steps': []}
    c.save(ROOT / 'claim-attempt.json', report)
    spec = importlib.util.spec_from_file_location('trace_core', CPU_ROOT / 'trace-core.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.GROUP = 'pocketfed_fpc_claim_20260913'
    trace = core.ScopedTrace()
    uncertain = False
    started = []
    try:
        trace.start()
        for unit in (*c.UNITS, DAEMON):
            print('FPC_CLAIM_START_UNIT ' + unit, flush=True)
            uncertain = True
            status = subprocess.Popen(['systemctl', 'start', unit]).wait(timeout=90)
            uncertain = False
            report['steps'].append({'unit': unit, 'status': status})
            if status:
                raise RuntimeError('service start failed: ' + unit)
            started.append(unit)
        pid = int(c.output(['systemctl', 'show', DAEMON, '-p', 'MainPID', '--value']))
        assert pid > 1
        assert c.sha(Path(f'/proc/{pid}/root/usr/lib64/libfprint-2.so.2.0.0')) == LIB_SHA
        tasks = sorted(int(p.name) for p in Path(f'/proc/{pid}/task').iterdir())
        (trace.instance / 'set_event_pid').write_text(' '.join(map(str, [os.getpid(), *tasks])))
        report['fprintd_pid'] = pid
        report['initial_tids'] = tasks
        print('FPC_CLAIM_TRACE_READY ' + json.dumps({'pid': pid, 'tids': tasks}), flush=True)
        assert not trace.errors and not trace.dropped
        # A DBus timeout does not prove the native worker has returned. Preserve
        # it and the secure service chain on every nonzero client outcome.
        uncertain = True
        status = subprocess.Popen([str(CLIENT)]).wait(timeout=120)
        report['client_status'] = status
        if status:
            raise RuntimeError('Claim client failed; native completion is uncertain')
        uncertain = False
        time.sleep(0.3)
    except Exception as error:
        report['error'] = str(error)
    finally:
        if not uncertain:
            try:
                for unit in reversed(started):
                    print('FPC_CLAIM_STOP_UNIT ' + unit, flush=True)
                    uncertain = True
                    status = subprocess.Popen(['systemctl', 'stop', unit]).wait(timeout=90)
                    uncertain = False
                    assert status == 0, unit
                report['clean_shutdown'] = True
                c.guard()
            except Exception as error:
                report['shutdown_error'] = str(error)
        if not uncertain:
            try:
                trace.close()
                report['owned_probes_removed'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        events = [r for r in trace.records if 'event' in r]
        sequence = ['app_enter', 'scm_enter', 'quirk_enter', 'quirk_exit', 'scm_exit', 'app_exit']
        complete = (len(events) >= 12 and len(events) % 6 == 0 and
                    [r['event'] for r in events] == sequence * (len(events) // 6) and
                    all(r.get('status', 0) == 0 for r in events))
        report.update(uncertain_call_pending=uncertain, trace=list(trace.records),
                      trace_errors=list(trace.errors), trace_records_dropped=trace.dropped,
                      complete_kernel_boundaries=complete)
        report['passed'] = (report.get('client_status') == 0 and complete and
                            report.get('clean_shutdown', False) and
                            report.get('owned_probes_removed', False) and
                            not uncertain and not trace.errors and not trace.dropped and
                            not report.get('error') and not report.get('shutdown_error'))
        print('FPC_CLAIM_KERNEL_RESULT ' + json.dumps(report, separators=(',', ':')), flush=True)
        c.save(ROOT / 'result.json', report)
        if uncertain:
            while True:
                time.sleep(30)


if __name__ == '__main__':
    os.umask(0o077)
    assert len(sys.argv) == 2 and sys.argv[1] in ('--stage', '--claim')
    stage() if sys.argv[1] == '--stage' else claim()
