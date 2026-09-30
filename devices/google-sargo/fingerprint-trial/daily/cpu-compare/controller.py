#!/usr/bin/python3
"""One daily initialization on a fixed CPU, retaining scoped kernel evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path('/var/tmp/sargo-fingerprint-cpu-compare-20260913')
BOOT = '0ac24861-f5de-4f09-8128-fd24c2f80070'
SERIAL = '994AY18RSD'
RELEASE = '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
PIN = '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
BINARY = Path('/usr/local/libexec/pocketfed-fpc-cpu-compare-20260913')
UNITS = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
         'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service')
MASKS = ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
output = lambda argv: subprocess.check_output(argv, text=True).strip()


def guard(check_installed_binary=True):
    assert os.geteuid() == 0 and ROOT.resolve() == ROOT
    assert stat.S_IMODE(ROOT.stat().st_mode) == 0o700 and ROOT.stat().st_uid == 0
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert os.uname().release == RELEASE
    args = Path('/proc/cmdline').read_text().split()
    assert [a for a in args if a.startswith('androidboot.serialno=')] == ['androidboot.serialno=' + SERIAL]
    assert output(['getenforce']) == 'Enforcing' and sha(Path('/etc/pam.d/phosh')) == PIN
    for unit in MASKS:
        path = Path('/etc/systemd/system') / unit
        assert path.is_symlink() and path.readlink() == Path('/dev/null')
        assert output(['systemctl', 'show', unit.replace('@.', '@cpu-check.'),
                       '-p', 'ActiveState', '--value']) == 'inactive'
    for unit in UNITS:
        assert output(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive'
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for name, digest in manifest['bundle'].items():
        path = ROOT / name
        assert not path.is_symlink() and sha(path) == digest, name
    if check_installed_binary:
        assert not BINARY.is_symlink() and sha(BINARY) == manifest['probe_sha256']
    return manifest


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(fd)
    os.close(fd)


def main():
    assert len(sys.argv) == 2 and sys.argv[1] in ('--cpu=7', '--cpu=1')
    os.umask(0o077)
    cpu = int(sys.argv[1][-1])
    manifest = guard()
    if cpu == 1:
        previous = json.loads((ROOT / 'cpu7/result.json').read_text())
        assert previous['passed'] and previous['boot_id'] == BOOT
    directory = ROOT / f'cpu{cpu}'
    directory.mkdir(mode=0o700)  # Consumed even on incomplete/failing attempt.
    report = {'serial': SERIAL, 'boot_id': BOOT, 'kernel': RELEASE, 'cpu': cpu,
              'probe_sha256': manifest['probe_sha256'], 'started_at': time.time(),
              'capture_started': False, 'credential_operations': False,
              'automatic_retry': False, 'steps': []}
    save(directory / 'attempt.json', report)
    spec = importlib.util.spec_from_file_location('trace_core', ROOT / 'trace-core.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.GROUP = f'pocketfed_fpc_daily_cpu{cpu}_20260913'
    trace = core.ScopedTrace()
    uncertain = False
    started = []
    try:
        trace.start()
        for unit in UNITS:
            print('FPC_CPU_START_UNIT ' + unit, flush=True)
            uncertain = True
            status = subprocess.Popen(['systemctl', 'start', unit]).wait(timeout=90)
            uncertain = False
            report['steps'].append({'unit': unit, 'status': status})
            print('FPC_CPU_UNIT_RESULT ' + json.dumps(report['steps'][-1]), flush=True)
            if status:
                raise RuntimeError('service startup failed: ' + unit)
            started.append(unit)
        assert not trace.errors and not trace.dropped
        # C pins and verifies its own affinity; no Python preexec_fn in this
        # threaded controller. The trace PID filter follows the forked child.
        uncertain = True
        child = subprocess.Popen([str(BINARY), sys.argv[1]])
        report['probe_pid'] = child.pid
        report['probe_status'] = child.wait(timeout=60)
        uncertain = False
        time.sleep(0.3)
    except Exception as error:
        report['error'] = str(error)
    finally:
        if not uncertain:
            try:
                for unit in reversed(started):
                    print('FPC_CPU_STOP_UNIT ' + unit, flush=True)
                    uncertain = True
                    status = subprocess.Popen(['systemctl', 'stop', unit]).wait(timeout=90)
                    uncertain = False
                    assert status == 0, 'clean stop failed: ' + unit
                report['clean_shutdown'] = True
            except Exception as error:
                report['shutdown_error'] = str(error)
        if not uncertain:
            try:
                trace.close()
                report['owned_probes_removed'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        report['uncertain_call_pending'] = uncertain
        report['trace'] = list(trace.records)
        report['trace_errors'] = list(trace.errors)
        report['trace_records_dropped'] = trace.dropped
        events = [r for r in trace.records if 'event' in r]
        report['passed'] = (report.get('probe_status') == 0 and
                            report.get('clean_shutdown', False) and
                            report.get('owned_probes_removed', False) and
                            not uncertain and not trace.errors and not trace.dropped and
                            not report.get('error') and not report.get('shutdown_error') and
                            core.complete_trace(trace.records) and
                            all(r['cpu'] == cpu and r['pid'] == report['probe_pid'] for r in events))
        print('FPC_CPU_RESULT ' + json.dumps(report, separators=(',', ':')), flush=True)
        save(directory / 'result.json', report)
        if uncertain:
            # Retain blocked caller and evidence until explicit whole-phone
            # recovery. A userspace timeout must not terminate secure calls.
            while True:
                time.sleep(30)


if __name__ == '__main__':
    main()
