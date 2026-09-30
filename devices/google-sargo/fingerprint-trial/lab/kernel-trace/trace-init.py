#!/usr/bin/python3
"""One test-sargo sensor initialization with scoped, metadata-only kprobes."""
import json
import os
from pathlib import Path
import re
import select
import subprocess
import threading
import time

RUN = 'sargo-fingerprint-lab-kernel-trace-20260913'
GROUP = 'pocketfed_fpc_init_20260913'
TRACE = Path('/sys/kernel/tracing')
EVENTS = {
    'app_enter': ('p', 'qcom_scm_qseecom_app_send', ''),
    'app_exit': ('r', 'qcom_scm_qseecom_app_send', ' status=$retval:s32'),
    'scm_enter': ('p', '__scm_smc_call', ''),
    'scm_exit': ('r', '__scm_smc_call', ' status=$retval:s32'),
    'quirk_enter': ('p', '__scm_smc_do_quirk', ''),
    'quirk_exit': ('r', '__scm_smc_do_quirk', ''),  # void: never fetch retval
}
# Discard the kprobe's rendered instruction/caller addresses and task name.
LINE = re.compile(r'^\s*.+-(\d+)\s+\[(\d+)\]\s+\S+\s+(\d+\.\d+):\s+(\w+):\s+(.*)$')


def startup_report_name(name):
    assert name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster')
    return 'kernel_trace_startup_' + name


def complete_trace(records):
    events = [record for record in records if 'event' in record]
    expected = ['app_enter', 'scm_enter', 'quirk_enter',
                'quirk_exit', 'scm_exit', 'app_exit'] * 2
    return ([record['event'] for record in events] == expected and
            all(record.get('status', 0) == 0 for record in events))


def metadata(line):
    match = LINE.fullmatch(line.strip())
    if not match:
        return None
    pid, cpu, stamp, event, detail = match.groups()
    if event == 'tracing_mark_write' and detail == 'FPC_TRACE_READY':
        return {'ready': True}
    if event not in EVENTS:
        return None
    result = {'pid': int(pid), 'cpu': int(cpu), 'time': stamp, 'event': event}
    if EVENTS[event][2]:
        value = re.search(r'\bstatus=(-?\d+)(?:\s|$)', detail)
        if value is None:
            raise ValueError('missing signed return status')
        result['status'] = int(value[1])
    return result


class ScopedTrace:
    def __init__(self):
        self.instance = TRACE / 'instances' / GROUP
        self.registered = []
        self.records = []
        self.errors = []
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.created = False
        self.dropped = 0

    def command(self, command):
        # O_APPEND is intentional: never truncate another task's event list.
        fd = os.open(TRACE / 'kprobe_events', os.O_WRONLY | os.O_APPEND)
        try:
            data = (command + '\n').encode()
            if os.write(fd, data) != len(data):
                raise OSError('short probe definition write')
        finally:
            os.close(fd)

    def start(self):
        assert (TRACE / 'kprobe_events').is_file()
        assert GROUP not in (TRACE / 'kprobe_events').read_text()
        self.instance.mkdir()  # Existing instance is never reused or cleared.
        self.created = True
        (self.instance / 'tracing_on').write_text('0')
        (self.instance / 'buffer_size_kb').write_text('64')
        (self.instance / 'trace_clock').write_text('mono')
        for event, (kind, symbol, fetch) in EVENTS.items():
            self.command(f'{kind}:{GROUP}/{event} {symbol}{fetch}')
            self.registered.append(event)
        (self.instance / 'set_event_pid').write_text(str(os.getpid()))
        (self.instance / 'options/event-fork').write_text('1')
        (self.instance / 'events' / GROUP / 'enable').write_text('1')
        (self.instance / 'tracing_on').write_text('1')
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()
        (self.instance / 'trace_marker').write_text('FPC_TRACE_READY\n')
        if not self.ready.wait(5) or self.errors:
            raise RuntimeError('trace relay did not confirm its marker')

    def read(self):
        fd = os.open(self.instance / 'trace_pipe', os.O_RDONLY | os.O_NONBLOCK)
        pending = b''
        try:
            while not self.stopping.is_set():
                if not select.select([fd], [], [], 0.1)[0]:
                    continue
                try:
                    pending += os.read(fd, 65536)
                except BlockingIOError:
                    continue
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    record = metadata(line.decode('ascii'))
                    if record is not None:
                        if len(self.records) >= 256:
                            self.dropped += 1
                            if self.dropped == 1:
                                print('FPC_KTRACE_LIMIT reached=256', flush=True)
                            continue
                        self.records.append(record)
                        print('FPC_KTRACE ' + json.dumps(record, separators=(',', ':')), flush=True)
                        if record.get('ready'):
                            self.ready.set()
        except Exception as error:
            self.errors.append(str(error))
        finally:
            os.close(fd)

    def close(self):
        if self.created:
            (self.instance / 'tracing_on').write_text('0')
            if (self.instance / 'events' / GROUP / 'enable').exists():
                (self.instance / 'events' / GROUP / 'enable').write_text('0')
            self.stopping.set()
            if self.thread:
                self.thread.join(2)
                assert not self.thread.is_alive(), 'trace reader did not stop'
            self.instance.rmdir()
        for event in reversed(self.registered):
            self.command(f'-:{GROUP}/{event}')


def main():
    from lab_report import emit
    assert os.geteuid() == 0
    cmdline = Path('/proc/cmdline').read_text().split()
    for option in ('androidboot.serialno=99NAY1AZG1', 'pocketfed.root_mode=usb',
                   'pocketfed.liveboot=' + RUN):
        assert cmdline.count(option) == 1
    assert os.uname().release == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    assert subprocess.check_output(['getenforce'], text=True).strip() == 'Enforcing'
    assert subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '/'], text=True).strip() == 'overlay'
    subprocess.run(['python3', '/usr/libexec/sargo-fingerprint-lab/guard-device.py'], check=True)
    report = {'run_id': RUN, 'serial': '99NAY1AZG1', 'steps': [],
              'capture_started': False, 'credential_operations': False,
              'rpmb_writes_allowed': False, 'automatic_retry': False}
    state = Path('/run/pocketfed-fingerprint-lab')
    with (state / 'kernel-trace-attempt.json').open('x') as stream:
        json.dump(report, stream)
    trace = ScopedTrace()
    uncertain = False
    started = []
    try:
        trace.start()
        for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster'):
            unit = 'pocketfed-fingerprint-lab-' + name + '.service'
            uncertain = True
            result = subprocess.run(['systemctl', 'start', unit], timeout=90)
            uncertain = False
            report['steps'].append({'unit': unit, 'status': result.returncode})
            emit(startup_report_name(name), report)
            if result.returncode:
                raise RuntimeError('startup failed: ' + unit)
            started.append(unit)
        if trace.errors:
            raise RuntimeError('trace relay failed before invocation')
        emit('kernel_trace_ready', {'run_id': RUN, 'serial': '99NAY1AZG1',
                                  'trace_marker_received': trace.ready.is_set()})
        # The child inherits the PID trace filter before exec or any secure call.
        # wait(timeout) does not send SIGKILL to a blocked secure caller.
        child = subprocess.Popen(['/usr/libexec/sargo-fingerprint-lab/initialize-once',
                                  '--initialize-once'])
        uncertain = True
        report['probe_status'] = child.wait(timeout=60)
        uncertain = False
        time.sleep(0.25)  # Allow the separate reader to drain completed return events.
        if trace.errors:
            raise RuntimeError('trace relay failed')
        for unit in reversed(started):
            uncertain = True
            result = subprocess.run(['systemctl', 'stop', unit], timeout=90)
            uncertain = False
            if result.returncode:
                raise RuntimeError('clean stop failed: ' + unit)
        report['clean_shutdown'] = True
    except Exception as error:
        report['error'] = str(error)
    finally:
        report['uncertain_call_pending'] = uncertain
        # Leave a pending secure caller and its tracing alive for UART recovery.
        if not uncertain:
            try:
                trace.close()
                report['owned_probes_removed'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        report['trace'] = list(trace.records)
        report['trace_errors'] = list(trace.errors)
        report['trace_records_dropped'] = trace.dropped
        report['passed'] = (report.get('probe_status') == 0 and
                            report.get('clean_shutdown', False) and
                            not uncertain and not trace.errors and not trace.dropped and
                            complete_trace(trace.records) and
                            not report.get('cleanup_error'))
        emit('kernel_trace_finished', report)
        if uncertain:
            # Keep the unit alive: systemd must not kill a timed-out child merely
            # because this controller exits. Explicit whole-guest recovery follows.
            while True:
                time.sleep(30)


if __name__ == '__main__':
    main()
