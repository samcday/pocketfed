#!/usr/bin/python3
"""One UART reboot after the recorded daily DEEP_SLEEP freeze; retain capture."""
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

REPO = Path(__file__).resolve().parents[4]
UART = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0'
SERIAL = '994AY18RSD'
BOOT = '4deb54c7-8d28-4239-94c4-545f86b5678c'
root = REPO / 'out/private/sargo-daily-loader-freeze-recovery-20260913'
old = REPO / 'out/private/sargo-daily-uart-20260913/uart.log'
data = old.read_bytes()
assert ('FPC_CLEANBOOT_UART_' + SERIAL + '_' + BOOT).encode() in data
assert b'FPC_TRACE 634.014089 tid=4387 cpu=6 tee.invoke.begin' in data
assert b'FPC_TRACE 634.013988 tid=4387 cpu=6 protocol.begin a=10 b=5' in data
assert b'FPC_CLAIM_ONLY Claim.error' in data
assert b'watchdog: BUG: soft lockup' in data
diagnostic = REPO / 'out/private/sargo-daily-loader-freeze-loglevel-20260913/uart.log'
assert b'sysrq: Loglevel set to 9' in diagnostic.read_bytes()
os.umask(0o077)
root.mkdir(mode=0o700)  # Existing attempt is never repeated or replaced.
locks = Path(tempfile.gettempdir()) / f'pocketfed-liveboot-locks-{os.getuid()}'
assert locks.is_dir() and not locks.is_symlink() and locks.stat().st_uid == os.getuid()
lock = (locks / (SERIAL + '.lock')).open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
assert subprocess.run(['fuser', UART], capture_output=True).returncode == 1
fd = os.open(UART, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
stopping = False


def stop(signum, frame):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    fcntl.ioctl(fd, termios.TIOCEXCL)
    attrs = termios.tcgetattr(fd)
    attrs[0] = attrs[1] = attrs[3] = 0
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[4] = attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    with (root / 'uart.log').open('xb', buffering=0) as output:
        record = {'pid': os.getpid(), 'uart': UART, 'serial': SERIAL,
                  'previous_boot': BOOT, 'started_at': time.time(),
                  'operation': 'SysRq reboot after captured secure-call freeze',
                  'held_locks': [SERIAL + '.lock'], 'global_lock': False,
                  'flash_erase_slot_change': False, 'repeat': False}
        with (root / 'attempt.json').open('x') as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        spec = importlib.util.spec_from_file_location('liveboot_uart', REPO / 'tools/liveboot/run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.uart_sysrq(fd, 'reboot')
        (root / 'transmitted.json').write_text(json.dumps({'at': time.time(),
                'acknowledgment': 'must be observed in UART/new boot; not implied by write'}) + '\n')
        print('Daily UART reboot request transmitted; capture remains active.', flush=True)
        while not stopping:
            if select.select([fd], [], [], 1)[0]:
                try:
                    block = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if block:
                    output.write(block)
        os.fsync(output.fileno())
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    fcntl.ioctl(fd, termios.TIOCNXCL)
    os.close(fd)
    lock.close()
print('Daily recovery capture closed.', flush=True)
