#!/usr/bin/env python3
"""Persistent UART daemon for the DB410c board.

Holds /dev/ttyUSB0 exclusively, appends everything read to --log,
and takes JSON request lines on a FIFO:
  {"send": "text", "pace": 0.002}   # text, optional per-byte sleep
  {"b64": "....",  "pace": 0.0}     # raw bytes, base64-encoded
  {"break": true}
  {"quit": true}
"""
import argparse, base64, errno, fcntl, json, os, select, sys, termios, time

p = argparse.ArgumentParser()
p.add_argument('--device', required=True)
p.add_argument('--log', required=True)
p.add_argument('--fifo', required=True)
a = p.parse_args()

if not os.path.exists(a.fifo):
    os.mkfifo(a.fifo, 0o600)

fd = os.open(a.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
fcntl.ioctl(fd, termios.TIOCEXCL)
s = termios.tcgetattr(fd)
s[0] = s[1] = s[3] = 0
s[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
s[4] = s[5] = termios.B115200
s[6][termios.VMIN] = s[6][termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW, s)

# open FIFO read-write so it never hits EOF when writers close
ffd = os.open(a.fifo, os.O_RDWR | os.O_NONBLOCK)
buf = b''
log = open(a.log, 'ab', buffering=0)
print('uartd ready dev=%s log=%s fifo=%s' % (a.device, a.log, a.fifo), flush=True)

def write_bytes(data, pace, block=0, delay=0.0):
    """Three pacing modes: per-byte (pace>0), block+delay, or free-run."""
    if block:
        for i in range(0, len(data), block):
            chunk = data[i:i + block]
            off = 0
            while off < len(chunk):
                if not select.select([], [fd], [], 10)[1]:
                    raise TimeoutError('UART write timed out')
                off += os.write(fd, chunk[off:])
            if delay:
                time.sleep(delay)
    elif pace <= 0:
        off = 0
        while off < len(data):
            if not select.select([], [fd], [], 10)[1]:
                raise TimeoutError('UART write timed out')
            off += os.write(fd, data[off:off + 64])
    else:
        for byte in data:
            if not select.select([], [fd], [], 10)[1]:
                raise TimeoutError('UART write timed out')
            os.write(fd, bytes([byte]))
            time.sleep(pace)

try:
    while True:
        ready, _, _ = select.select([fd, ffd], [], [], 1)
        if fd in ready:
            try:
                data = os.read(fd, 65536)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    data = b''
                else:
                    raise
            if data:
                log.write(data)
        if ffd in ready:
            try:
                chunk = os.read(ffd, 1 << 20)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    chunk = b''
                else:
                    raise
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                if not line.strip():
                    continue
                try:
                    act = json.loads(line)
                except Exception:
                    continue
                if act.get('quit'):
                    raise SystemExit(0)
                if act.get('break'):
                    termios.tcsendbreak(fd, 0)
                pace = float(act.get('pace', 0.002))
                block = int(act.get('block', 0))
                delay = float(act.get('delay', 0.0))
                if 'b64' in act:
                    write_bytes(base64.b64decode(act['b64']), pace, block, delay)
                elif 'send' in act:
                    write_bytes(act['send'].encode(), pace, block, delay)
finally:
    try:
        fcntl.ioctl(fd, termios.TIOCNXCL)
    except Exception:
        pass
    os.close(fd)
