#!/usr/bin/python3
"""Run 50 ordinary Claim/Release cycles across 10 installed fprintd lifetimes.

The existing client only lists enrolled finger names, claims the sensor and
releases it. It never starts capture, enrolls, deletes or requests a credential.
No native process is killed or automatically retried after an uncertain result.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/var/tmp/sargo-fingerprint-pool-20260913')
RELEASE = '7.1.2-0.pocketfed.sdm670.12.fc46.aarch64'
CLIENT = Path('/usr/local/libexec/pocketfed-fpc-claim-only-20260912')
CLIENT_SHA = '55a4f37ea5cba8b26eebe4830f13c9f8a5891133d665a694ac7fd26b1dfa2419'
UNITS = ('qsee-supplicant.service', 'qsee-shared-loader@cmnlib64.service',
         'qsee-app-loader@fpctzappfingerprint.service',
         'pocketfed-keymaster-startup.service', 'fprintd.service')


def out(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def emit(event, **fields):
    record = {'event': event, 'monotonic': time.monotonic(), **fields}
    line = 'FPC_KERNEL12_LIFETIMES ' + json.dumps(record, separators=(',', ':'))
    print(line, flush=True)
    with open('/dev/kmsg', 'w') as stream:
        stream.write('<6>' + line + '\n')


def main():
    assert os.geteuid() == 0 and Path(__file__).resolve().parent == ROOT
    assert 'androidboot.serialno=994AY18RSD' in Path('/proc/cmdline').read_text().split()
    assert os.uname().release == RELEASE and out('getenforce') == 'Enforcing'
    assert sha(Path('/etc/pam.d/phosh')) == '695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
    assert sha(CLIENT) == CLIENT_SHA
    identity = json.loads((ROOT / 'candidate-identity.json').read_text())
    state = json.loads(out('rpm-ostree', 'status', '--json'))
    assert state['transaction'] is None and not any(d.get('staged') for d in state['deployments'])
    deployment = next(d for d in state['deployments'] if d['booted'])
    assert deployment['container-image-reference-digest'] == identity['manifest']
    assert not out('modinfo', '-k', RELEASE, '-p', 'qseecomtee')
    for unit in ('phosh-fingerprint-auth.socket', 'phosh-fingerprint-auth@.service'):
        assert os.readlink('/etc/systemd/system/' + unit) == '/dev/null'
    assert subprocess.run(['pgrep', '-f', '(^|/)(gnome-control-center|gnome-control-center-fingerprint-20260913)( |$)'],
                          stdout=subprocess.DEVNULL).returncode == 1, 'Close Settings first'
    assert all(out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive'
               for unit in UNITS)
    assert not Path('/run/systemd/system/fprintd.service.d').exists()
    expected = json.loads((ROOT / 'installed-acceptance-inputs-v2.json').read_text())
    for path, digest in expected['files'].items():
        assert sha(Path(path)) == digest, path
    result = {'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'kernel': RELEASE, 'deployment': deployment['checksum'],
              'started_at': time.time(), 'cycles': [], 'lifetimes': [],
              'capture_started': False, 'credential_operations': False}
    evidence = ROOT / 'claim-lifetimes'
    evidence.mkdir(mode=0o700)
    printk = Path('/proc/sys/kernel/printk')
    result['previous_console_loglevel'] = int(printk.read_text().split()[0])
    save(evidence / 'attempt.json', result)
    # Installed boots use quiet. Make the bounded informational markers visible
    # to the already attached UART capture for the duration of this test.
    printk.write_text('7\n')
    # Keep an uncertain startup alive for UART inspection, as the existing
    # firmware-service lifetime overrides already do. This changes no driver,
    # CPU affinity, sandbox, D-Bus name or device permissions.
    dropdir = Path('/run/systemd/system/fprintd.service.d')
    dropdir.mkdir()
    dropin = dropdir / '99-pool-acceptance.conf'
    dropin.write_text('[Service]\nTimeoutStartSec=infinity\nTimeoutStopSec=infinity\nRestart=no\n')
    result['temporary_timeout_override'] = {'path': str(dropin), 'sha256': sha(dropin)}
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # The Phosh clients remain masked throughout this measured sequence.
    subprocess.run(['systemctl', 'unmask', 'qsee-supplicant.service', 'fprintd.service'], check=True)
    try:
        for lifetime in range(1, 11):
            emit('lifetime-start', lifetime=lifetime)
            for unit in UNITS:
                subprocess.run(['systemctl', 'start', unit], check=True)
                assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'active', unit
            pid = int(out('systemctl', 'show', 'fprintd.service', '-p', 'MainPID', '--value'))
            assert pid > 1
            library = '/usr/lib64/libfprint-2.so.2.0.0'
            assert sha(Path(f'/proc/{pid}/root' + library)) == expected['files'][library]
            for offset in range(1, 6):
                number = (lifetime - 1) * 5 + offset
                assert int(out('systemctl', 'show', 'fprintd.service', '-p', 'MainPID', '--value')) == pid
                emit('claim-start', cycle=number, lifetime=lifetime, daemon_pid=pid)
                with (evidence / f'cycle-{number:02d}.log').open('xb') as log:
                    process = subprocess.run([str(CLIENT)], stdout=log, stderr=subprocess.STDOUT)
                text = (evidence / f'cycle-{number:02d}.log').read_text()
                record = {'cycle': number, 'lifetime': lifetime, 'daemon_pid': pid,
                          'returncode': process.returncode,
                          'log_sha256': sha(evidence / f'cycle-{number:02d}.log')}
                save(evidence / f'cycle-{number:02d}.json', record)
                result['cycles'].append(record)
                assert process.returncode == 0 and 'FPC_CLAIM_ONLY complete; capture_started=false' in text
                assert text.count('Claim.end') == 1 and text.count('Release.end') == 1
                emit('claim-complete', **record)
            stopped = []
            for unit in reversed(UNITS):
                emit('service-stop', lifetime=lifetime, unit=unit)
                subprocess.run(['systemctl', 'stop', unit], check=True)
                assert out('systemctl', 'show', unit, '-p', 'ActiveState', '--value') == 'inactive', unit
                stopped.append(unit)
                emit('service-stopped', lifetime=lifetime, unit=unit)
            result['lifetimes'].append({'lifetime': lifetime, 'pid': pid, 'stopped': stopped})
            emit('lifetime-complete', lifetime=lifetime)
        assert len({x['pid'] for x in result['lifetimes']}) == 10
        subprocess.run(['systemctl', 'mask', 'fprintd.service'], check=True)
        dropin.unlink()
        dropdir.rmdir()
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        result['temporary_timeout_override_removed'] = True
        result['passed'] = True
    except Exception as error:
        result.update(passed=False, error=repr(error), cleanup_attempted_after_failure=False)
        # Masking only blocks new activation; it does not stop a pending worker.
        subprocess.run(['systemctl', 'mask', 'fprintd.service'], check=True)
        raise
    finally:
        result['finished_at'] = time.time()
        save(evidence / 'result.json', result)
        emit('result', passed=result.get('passed', False), cycles=len(result['cycles']),
             lifetimes=len(result['lifetimes']))
        printk.write_text(str(result['previous_console_loglevel']) + '\n')


if __name__ == '__main__':
    main()
