#!/usr/bin/python3
"""Capture daily sam-sargo UART privately; optional diagnostic SysRq, never reboot."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import termios
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
# Accept old invocation scripts, but daily UART capture always owns only its
# assigned handset. It neither serves USB storage nor reserves other devices.
p.add_argument('--uart-only', action='store_true', help=argparse.SUPPRESS)
p.add_argument('--diagnostic', choices=('loglevel-9', 'blocked-tasks', 'tasks', 'cpu-backtraces', 'replay-log'))
args = p.parse_args()
os.umask(0o077)
root = args.output.resolve()
assert root.is_dir() and root.stat().st_mode & 0o777 == 0o700
uart_path = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0'
locks = Path(tempfile.gettempdir()) / f'pocketfed-liveboot-locks-{os.getuid()}'
assert locks.is_dir() and not locks.is_symlink() and locks.stat().st_uid == os.getuid()
lock_names = ('994AY18RSD.lock',)
handles = [(locks / name).open('a') for name in lock_names]
for handle in handles:
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
assert subprocess.run(['fuser', uart_path], capture_output=True).returncode == 1
fd = os.open(uart_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
stopping = False

def stop(signum, frame):
    global stopping
    stopping = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def diagnostic(fd, name):
    # Use the same bounded FTDI BREAK mechanism as tools/liveboot/run.py.
    # These commands only expose diagnostics; no reboot or process-kill key.
    source = Path(__file__).resolve().parents[4] / 'tools/liveboot/run.py'
    spec = importlib.util.spec_from_file_location('liveboot_uart_deadline', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {'loglevel-9': b'9', 'blocked-tasks': b'w', 'tasks': b't',
               'cpu-backtraces': b'l', 'replay-log': b'R'}[name]
    normal = termios.tcgetattr(fd)
    slow = list(normal)
    slow[4] = slow[5] = termios.B300
    with module.uart_control_deadline():
        try:
            termios.tcsetattr(fd, termios.TCSANOW, slow)
            if os.write(fd, b'\0') != 1:
                raise OSError('short UART BREAK write')
            termios.tcdrain(fd)
            time.sleep(0.1)
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, normal)
        time.sleep(0.2)
        if os.write(fd, payload) != 1:
            raise OSError('short diagnostic SysRq write')
        termios.tcdrain(fd)

try:
    fcntl.ioctl(fd, termios.TIOCEXCL)
    attrs = termios.tcgetattr(fd)
    attrs[0] = attrs[1] = attrs[3] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[4] = attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    with (root / 'uart.log').open('xb', buffering=0) as output:
        (root / 'capture.json').write_text(json.dumps({
            'pid': os.getpid(), 'uart': uart_path, 'baud': 115200,
            'started_at': time.time(), 'serial_input_sent': False,
            'identity': 'pending marker from serial-verified daily SSH session',
            'held_locks': list(lock_names), 'uart_only': True,
        }, indent=2) + '\n')
        if args.diagnostic:
            # Retain the attempt even if the serial write or acknowledgment fails.
            (root / 'diagnostic-attempt.json').write_text(json.dumps({
                'diagnostic': args.diagnostic, 'attempted_at': time.time(),
                'identity_basis': 'Sam confirmed daily sam-sargo on UART while frozen',
                'reboot': False,
            }, indent=2) + '\n')
            diagnostic(fd, args.diagnostic)
            metadata_path = root / 'capture.json'
            metadata = json.loads(metadata_path.read_text())
            metadata['serial_input_sent'] = True
            metadata['diagnostic'] = args.diagnostic
            metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
            (root / 'diagnostic-transmitted.json').write_text(json.dumps({
                'diagnostic': args.diagnostic, 'acknowledgment': 'check uart.log',
                'serial_input_sent': True, 'reboot': False,
            }, indent=2) + '\n')
            print('Diagnostic SysRq sent; private capture active; check device acknowledgment.', flush=True)
        else:
            print('Private UART capture active; no serial input is sent.', flush=True)
        while not stopping:
            ready, _, _ = select.select([fd], [], [], 1)
            if ready:
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if data:
                    output.write(data)
        os.fsync(output.fileno())
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    fcntl.ioctl(fd, termios.TIOCNXCL)
    os.close(fd)
    for handle in handles:
        handle.close()
print('UART capture closed.', flush=True)
