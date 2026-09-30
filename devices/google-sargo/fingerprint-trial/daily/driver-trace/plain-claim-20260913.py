#!/usr/bin/python3
"""Five successful Claim/Release cycles without kernel probes or trace readers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/var/tmp/sargo-fingerprint-plain-claim-20260913')
BOOT = '15c464d5-16f8-44fe-a3e0-96e6ee380310'
DAEMON = 'pocketfed-fpc-plain-daemon-20260913.service'
TRIAL = 'pocketfed-fpc-plain-claim-20260913.service'
UNITS = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
         'qsee-app-loader@fpctzappfingerprint.service', 'pocketfed-keymaster-startup.service')
LIB = Path('/usr/local/lib64/pocketfed-fingerprint-trace-20260912/libfprint-2.so.2.0.0')
CLIENT = Path('/usr/local/libexec/pocketfed-fpc-claim-only-20260912')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
out = lambda argv: subprocess.check_output(argv, text=True).strip()


def save(name, data):
    with (ROOT / name).open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def guard():
    assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
    assert ROOT.resolve() == ROOT and ROOT.stat().st_uid == 0 and ROOT.stat().st_mode & 0o777 == 0o700
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT
    assert [a for a in Path('/proc/cmdline').read_text().split() if a.startswith('androidboot.serialno=')] == ['androidboot.serialno=994AY18RSD']
    assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    assert out(['getenforce']) == 'Enforcing'
    assert sha(Path('/etc/pam.d/phosh')) == '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
    assert sha(LIB) == '274ac3814562947589a31fc90e03e6c7d0974eee8bbb3b19cdbc58ff7fb8d937'
    assert sha(CLIENT) == '55a4f37ea5cba8b26eebe4830f13c9f8a5891133d665a694ac7fd26b1dfa2419'
    for u in ('fprintd.service', 'phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service'):
        assert os.readlink(Path('/etc/systemd/system') / u) == '/dev/null'
        assert out(['systemctl', 'show', u.replace('@.', '@plain-check.'), '-p', 'ActiveState', '--value']) == 'inactive'
    for u in UNITS:
        assert out(['systemctl', 'show', u, '-p', 'ActiveState', '--value']) == 'inactive', u
    assert not list(Path('/sys/kernel/tracing/instances').iterdir())
    assert not Path('/sys/kernel/tracing/kprobe_events').read_text().strip()


def stage():
    guard()
    units = Path('/run/systemd/system')
    old = json.loads(Path('/var/tmp/sargo-fingerprint-cleanboot-claim-20260913/stage-attempt.json').read_text())
    for path, contents in old['fragments'].items():
        assert Path(path).read_text() == contents
    with (units / DAEMON).open('x') as f:
        f.write('\n'.join(old['fragments'].values()))
        f.write(f'\n[Service]\nBindReadOnlyPaths={LIB}:/usr/lib64/libfprint-2.so.2.0.0\nTimeoutStartSec=infinity\n')
    with (units / TRIAL).open('x') as f:
        f.write(f'''[Unit]
Description=Five daily fingerprint Claim/Release checks without kernel tracing
ConditionKernelCommandLine=androidboot.serialno=994AY18RSD
[Service]
Type=exec
ExecStart=/usr/bin/python3 -u {Path(__file__).resolve()} --run
Restart=no
TimeoutStartSec=infinity
TimeoutStopSec=infinity
LimitCORE=0
UMask=0077
StandardOutput=append:/dev/ttyMSM0
StandardError=append:/dev/ttyMSM0
''')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    for unit in (DAEMON, TRIAL):
        assert out(['systemctl', 'show', unit, '-p', 'LoadState', '--value']) == 'loaded'
        assert out(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']) == 'inactive'
    save('staged.json', {'boot_id': BOOT, 'script_sha256': sha(Path(__file__)),
                        'units': {u: sha(units / u) for u in (DAEMON, TRIAL)}})
    print('Plain Claim trial staged; no device opened.')


def run():
    guard()
    staged = json.loads((ROOT / 'staged.json').read_text())
    assert staged['boot_id'] == BOOT and staged['script_sha256'] == sha(Path(__file__))
    for unit, digest in staged['units'].items():
        assert sha(Path('/run/systemd/system') / unit) == digest
    report = {'serial': '994AY18RSD', 'boot_id': BOOT, 'kernel_probes': False,
              'cpu_affinity_changed': False, 'capture_started': False,
              'credential_recovery': False, 'planned_claims': 5, 'claims': [], 'steps': []}
    save('attempt.json', report)
    started = []
    pending = False
    relay = subprocess.Popen(['/usr/bin/journalctl', '--follow', '--boot', '--lines=0',
                              '--no-pager', '--output=short-monotonic', '--unit=' + DAEMON])
    try:
        for unit in (*UNITS, DAEMON):
            print('FPC_PLAIN_START ' + unit, flush=True)
            pending = True
            status = subprocess.Popen(['systemctl', 'start', unit]).wait(timeout=90)
            pending = False
            report['steps'].append({'unit': unit, 'status': status})
            assert status == 0, unit
            started.append(unit)
        pid = int(out(['systemctl', 'show', DAEMON, '-p', 'MainPID', '--value']))
        assert pid > 1 and sha(Path(f'/proc/{pid}/root/usr/lib64/libfprint-2.so.2.0.0')) == sha(LIB)
        for number in range(1, 6):
            assert int(out(['systemctl', 'show', DAEMON, '-p', 'MainPID', '--value'])) == pid
            print(f'FPC_PLAIN_CYCLE_BEGIN number={number}', flush=True)
            pending = True
            status = subprocess.Popen([str(CLIENT)]).wait(timeout=120)
            report['claims'].append({'number': number, 'status': status})
            assert status == 0, 'Client error does not prove native completion'
            pending = False
            print(f'FPC_PLAIN_CYCLE_END number={number} status=0', flush=True)
            time.sleep(1)
    except Exception as error:
        report['error'] = repr(error)
    finally:
        if not pending:
            try:
                for unit in reversed(started):
                    pending = True
                    status = subprocess.Popen(['systemctl', 'stop', unit]).wait(timeout=90)
                    pending = False
                    assert status == 0, unit
                report['clean_shutdown'] = True
                relay.terminate()  # Journal reader only; no kernel trace reader.
                relay.wait(timeout=5)
            except Exception as error:
                report['shutdown_error'] = repr(error)
        report['uncertain_call_pending'] = pending
        report['passed'] = (len(report['claims']) == 5 and all(r['status'] == 0 for r in report['claims'])
                            and not pending and report.get('clean_shutdown', False)
                            and not report.get('error') and not report.get('shutdown_error'))
        print('FPC_PLAIN_RESULT ' + json.dumps(report, separators=(',', ':')), flush=True)
        save('result.json', report)
        if pending:
            while True:
                time.sleep(30)


if __name__ == '__main__':
    os.umask(0o077)
    assert len(sys.argv) == 2 and sys.argv[1] in ('--stage', '--run')
    stage() if sys.argv[1] == '--stage' else run()
