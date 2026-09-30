#!/usr/bin/python3
"""Trace two successful fprintd Claim/Release cycles in a temporary copy of its service.

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

ROOT = Path('/var/tmp/sargo-fingerprint-loader-claim-20260913')
sys.path.insert(0, str(ROOT))
import trial_common as c

DAEMON = 'pocketfed-fpc-cleanboot-daemon-20260913.service'
TRIAL = 'pocketfed-fpc-loader-claim-20260913.service'
LIB = Path('/usr/local/lib64/pocketfed-fingerprint-trace-20260912/libfprint-2.so.2.0.0')
LIB_SHA = '274ac3814562947589a31fc90e03e6c7d0974eee8bbb3b19cdbc58ff7fb8d937'
CLIENT = Path('/usr/local/libexec/pocketfed-fpc-claim-only-20260912')
CLIENT_SHA = '55a4f37ea5cba8b26eebe4830f13c9f8a5891133d665a694ac7fd26b1dfa2419'
FRAGMENTS = ('/usr/lib/systemd/system/fprintd.service',
             '/usr/lib/systemd/system/fprintd.service.d/90-fpc-qsee.conf',
             '/etc/systemd/system/fprintd.service.d/99-fingerprint-lifetime.conf')


def closed_claim_calls(records):
    # Listener handling can make several SCM calls inside one application call.
    # Validate nested boundaries per thread, not an assumed six-event pattern.
    stacks = {}
    calls = 0
    parents = {'app_enter': [], 'scm_enter': ['app'], 'quirk_enter': ['app', 'scm']}
    for record in records:
        if 'event' not in record:
            continue
        event = record['event']
        stack = stacks.setdefault(record['pid'], [])
        if event.endswith('_enter'):
            if event not in parents or stack != parents[event]:
                return False
            stack.append(event.removesuffix('_enter'))
        else:
            if not stack or event != stack[-1] + '_exit' or record.get('status', 0):
                return False
            calls += event == 'app_exit'
            stack.pop()
    return calls >= 4 and all(not stack for stack in stacks.values())


def guard():
    c.guard()
    assert ROOT.resolve() == ROOT and ROOT.stat().st_uid == 0
    assert ROOT.stat().st_mode & 0o777 == 0o700
    assert c.sha(LIB) == LIB_SHA and c.sha(CLIENT) == CLIENT_SHA
    assert Path(__file__).resolve().parent == ROOT
    # Settings has no reason to share this deliberately isolated DBus lifetime.
    assert subprocess.run(['pgrep', '-f', '^/usr/bin/gnome-control-center'],
                          stdout=subprocess.DEVNULL).returncode == 1


def stage():
    guard()
    units = Path('/run/systemd/system')
    assert not os.path.lexists(units / TRIAL)
    old = json.loads(Path('/var/tmp/sargo-fingerprint-cleanboot-claim-20260913/staged.json').read_text())
    assert c.sha(units / DAEMON) == old['unit_sha256'][DAEMON]
    assert c.sha(Path(FRAGMENTS[1])) == 'c7a475b77dd740730b825259bc6731664d27a91f6b1c7b08e697b44340946c37'
    assert c.sha(Path(FRAGMENTS[2])) == 'b0e2ad5a73d04139724b4af90a173813b6893d2f478755c9d88d39bf2654d882'
    contents = {p: Path(p).read_text() for p in FRAGMENTS}
    c.save(ROOT / 'stage-attempt.json', {'serial': c.SERIAL, 'boot_id': c.BOOT,
                                       'fragments': contents})
    # Reuse the unchanged, loaded/inactive daemon; no duplicate bus registration.
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
              'common_sha256': c.sha(ROOT / 'trial_common.py'),
              'trace_sha256': c.sha(ROOT / 'trace-core.py'),
              'unit_sha256': {name: c.sha(units / name) for name in (DAEMON, TRIAL)},
              'source_sha256': {p: c.sha(Path(p)) for p in FRAGMENTS},
              'sensor_opened': False}
    c.save(ROOT / 'staged.json', record)
    for unit in (DAEMON, TRIAL):
        assert c.output(['systemctl', 'show', unit, '-p', 'LoadState', '--value']) == 'loaded'
        assert c.output(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive'
    print('Clean-boot daemon and controller verified loaded and inactive.')


def claim():
    guard()
    staged = json.loads((ROOT / 'staged.json').read_text())
    assert staged['boot_id'] == c.BOOT and staged['script_sha256'] == c.sha(Path(__file__))
    assert staged['common_sha256'] == c.sha(ROOT / 'trial_common.py')
    assert staged['trace_sha256'] == c.sha(ROOT / 'trace-core.py')
    for name, digest in staged['unit_sha256'].items():
        assert c.sha(Path('/run/systemd/system') / name) == digest
    for path, digest in staged['source_sha256'].items():
        assert c.sha(Path(path)) == digest
    assert c.output(['systemctl', 'show', DAEMON, '-p', 'ActiveState', '--value']) == 'inactive'
    report = {'serial': c.SERIAL, 'boot_id': c.BOOT, 'kernel': c.RELEASE,
              'started_at': time.time(), 'capture_started': False,
              'credential_operations': False, 'automatic_retry': False,
              'operations': ['GetDefaultDevice', 'ListEnrolledFingers', 'Claim', 'Release'],
              'planned_claims': 2, 'claim_results': [],
              'steps': []}
    c.save(ROOT / 'claim-attempt.json', report)
    spec = importlib.util.spec_from_file_location('trace_core', ROOT / 'trace-core.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.GROUP = 'pocketfed_fpc_loader_claim_20260913'
    core.EVENTS.update({
        'load_enter': ('p', 'qcom_scm_qseecom_app_load', ''),
        'load_exit': ('r', 'qcom_scm_qseecom_app_load', ' status=$retval:s32'),
        'library_enter': ('p', 'qcom_scm_qseecom_load_service', ''),
        'library_exit': ('r', 'qcom_scm_qseecom_load_service', ' status=$retval:s32'),
    })
    trace = core.ScopedTrace()
    uncertain = False
    started = []
    relay = None
    try:
        trace.start()
        # PID1 forks the unit processes. Follow these new processes only during
        # startup, emitting event names, PIDs, CPUs, times and signed returns.
        (trace.instance / 'set_event_pid').write_text(f'1 {os.getpid()}')
        relay = subprocess.Popen(['/usr/bin/journalctl', '--follow', '--boot', '--lines=0',
                                  '--no-pager', '--output=short-monotonic', '--unit=' + DAEMON])
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
        time.sleep(0.3)
        report['claim_trace_start'] = len(trace.records)
        report['fprintd_pid'] = pid
        report['initial_tids'] = tasks
        print('FPC_CLAIM_TRACE_READY ' + json.dumps({'pid': pid, 'tids': tasks}), flush=True)
        assert not trace.errors and not trace.dropped
        # A DBus timeout does not prove the native worker has returned. Preserve
        # it and the secure service chain on every nonzero client outcome.
        for number in (1, 2):
            assert int(c.output(['systemctl', 'show', DAEMON, '-p', 'MainPID', '--value'])) == pid
            print(f'FPC_CLAIM_CYCLE_BEGIN number={number} daemon_pid={pid}', flush=True)
            uncertain = True
            status = subprocess.Popen([str(CLIENT)]).wait(timeout=120)
            report['claim_results'].append({'cycle': number, 'status': status})
            if status:
                raise RuntimeError('Claim client failed; native completion is uncertain')
            uncertain = False
            print(f'FPC_CLAIM_CYCLE_END number={number} status={status}', flush=True)
            if number == 1:
                time.sleep(5)
        report['client_status'] = 0
        time.sleep(0.3)
    except Exception as error:
        report['error'] = repr(error)
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
                report['shutdown_error'] = repr(error)
        if not uncertain:
            try:
                trace.close()
                report['owned_probes_removed'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        if not uncertain and relay is not None:
            relay.terminate()  # Only the journal reader, never a secure caller.
            relay.wait(timeout=5)
        claim_records = trace.records[report.get('claim_trace_start', len(trace.records)):]
        complete = closed_claim_calls(claim_records)
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
