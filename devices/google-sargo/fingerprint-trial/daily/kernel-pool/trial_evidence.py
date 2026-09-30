#!/usr/bin/python3
"""Preserve diagnostic child output without a controlling console or timeout kill."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time


class Evidence:
    def __init__(self, root, sink=None):
        self.root = Path(root)
        self.events = (self.root / 'events.jsonl').open('x', buffering=1)
        self.errors = []
        self.fd = None
        if sink is None:
            self.fd = os.open('/dev/kmsg', os.O_WRONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            sink = lambda data: os.write(self.fd, data)
        self.sink = sink

    def emit(self, marker, value):
        line = marker + ' ' + json.dumps(value, separators=(',', ':'), ensure_ascii=True)
        data = ('<6>' + line + '\n').encode()
        if len(data) > 900:
            raise ValueError('diagnostic marker exceeds one bounded kernel-log record')
        try:
            self.events.write(json.dumps({'monotonic': time.monotonic(), 'line': line}) + '\n')
        except OSError as error:
            self.errors.append('event file: ' + repr(error))
        try:
            if self.sink(data) != len(data):
                raise OSError('short kernel-log write')
        except OSError as error:
            # Evidence loss must never cancel an in-flight native/secure call.
            self.errors.append(repr(error))
            try:
                self.events.write(json.dumps({'channel_error': repr(error)}) + '\n')
            except OSError:
                pass

    def native_line(self, stream, raw):
        text = raw.decode('utf-8', errors='backslashreplace')
        offset = 0
        while True:
            count = min(len(text), 600)
            while len(json.dumps({'stream': stream, 'offset': offset, 'text': text[:count]},
                                 ensure_ascii=True).encode()) > 800:
                count //= 2
            self.emit('FPC_POOL_NATIVE_OUTPUT',
                      {'stream': stream, 'offset': offset, 'text': text[:count]})
            text = text[count:]
            offset += count
            if not text:
                return

    def close(self):
        self.events.close()
        if self.fd is not None:
            os.close(self.fd)


def run_native(command, root, evidence):
    """Drain both pipes to EOF, wait without killing, persist status before returning."""
    root = Path(root)
    result = {'command': command, 'started_monotonic': time.monotonic(),
              'returncode': None, 'stdout_lines': [], 'stderr_lines': []}
    evidence.emit('FPC_POOL_NATIVE_LAUNCH', {'argv': command, 'timeout_kill': False})
    with ExitStack() as stack:
        streams = {name: stack.enter_context((root / ('native-' + name + '.log')).open('xb'))
                   for name in ('stdout', 'stderr')}
        digests = {name: hashlib.sha256() for name in streams}
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       bufsize=0, start_new_session=True)
        except OSError as error:
            result['launch_error'] = repr(error)
        else:
            result['pid'] = process.pid
            evidence.emit('FPC_POOL_NATIVE_STARTED', {'pid': process.pid})
            selector = stack.enter_context(selectors.DefaultSelector())
            pending = {name: b'' for name in streams}
            for name in streams:
                pipe = stack.enter_context(getattr(process, name))
                selector.register(pipe, selectors.EVENT_READ, name)

            def emit_pending(name, final=False):
                while b'\n' in pending[name] or len(pending[name]) >= 4096 or (final and pending[name]):
                    split = pending[name].find(b'\n')
                    if 0 <= split < 4096:
                        raw, pending[name] = pending[name][:split], pending[name][split + 1:]
                    else:
                        raw, pending[name] = pending[name][:4096], pending[name][4096:]
                    evidence.native_line(name, raw)
                    # This diagnostic emits only stage names, numbers and statuses.
                    result[name + '_lines'].append(raw.decode('utf-8', errors='backslashreplace'))

            while selector.get_map():
                for key, _ in selector.select():
                    name = key.data
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        emit_pending(name, final=True)
                        continue
                    try:
                        streams[name].write(data)
                        streams[name].flush()
                    except OSError as error:
                        evidence.errors.append(name + ' file: ' + repr(error))
                    digests[name].update(data)
                    pending[name] += data
                    emit_pending(name)
            result['returncode'] = process.wait()
        result['sha256'] = {name: digest.hexdigest() for name, digest in digests.items()}
    result['finished_monotonic'] = time.monotonic()
    result['evidence_errors'] = list(evidence.errors)
    # This file and UART event precede every loader-stop request in the caller.
    evidence.emit('FPC_POOL_NATIVE_RESULT',
                  {'returncode': result['returncode'], 'launch_error': result.get('launch_error'),
                   'elapsed_seconds': result['finished_monotonic'] - result['started_monotonic'],
                   'evidence_errors': len(result['evidence_errors'])})
    result['evidence_errors'] = list(evidence.errors)
    with (root / 'native-result.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return result


def completed_sequence(result):
    """Require the designed native sequence, not just process exit or elapsed time."""
    required = ('FPC_CPU_READY cpu=7 ',
                'FPC_INIT_RESULT transport=0 outer=0 command=0',
                'FPC_INIT_CMA_BEGIN count=1000 bytes=8192 cpu=7',
                'FPC_INIT_CMA_PROGRESS completed=1000',
                'FPC_INIT_CMA_END status=0',
                'FPC_SLEEP_RESULT transport=0 outer=0 command=0',
                'FPC_CPU_FINISHED cpu=7 status=0 capture_started=false')
    lines = iter(result['stdout_lines'])
    ordered = all(any(line.startswith(marker) for line in lines) for marker in required)
    close_ok = any(' tee.close.end a=0 b=0 status=0' in line for line in result['stderr_lines'])
    return result['returncode'] == 0 and ordered and close_ok and not result['evidence_errors']
