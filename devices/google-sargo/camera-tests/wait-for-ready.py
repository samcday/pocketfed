#!/usr/bin/env python3
"""Gate one camera capture on a fresh hardware volume-key gesture.

The Sargo trial starts face-down. Readiness is never inferred from elapsed
time: after this helper reports WAITING, the operator must pick the phone up,
aim the rear camera, and give a fresh Volume Up press+release. A short settling
countdown then gives time to hold still before exactly one capture command is
authorized. Volume Down cancels at any point, including during the countdown.

Capable devices are found through the Linux evdev API (EVIOCGBIT/EVIOCGKEY/
EVIOCGNAME). This helper never reads or writes GPIO, and never touches
/sys/kernel/debug/gpio. Optional EVIOCGRAB is off by default and, when enabled,
is scoped to the capable devices and released on every exit path.

Integration contract, one line per transition on stdout (also serial/log):

    pocketfed-camera-readiness: state=<state> detail="<detail>" instruct="<text>"

States: discovering, waiting, settling, authorized, cancelled, timeout,
capturing, capture-failed, complete. An optional private status file and an
optional existing-UI notify hook mirror the same state. See readiness.md.

Exit status: 0 authorized (and any capture command succeeded), 2 cancelled,
3 timed out waiting for readiness, 4 capture command failed, 130 interrupted.
"""

import argparse
import errno
import fcntl
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import time


PREFIX = "pocketfed-camera-readiness"

EV_SYN = 0
EV_KEY = 1
SYN_DROPPED_CODE = 3
KEY_VOLUMEDOWN = 114
KEY_VOLUMEUP = 115
KEY_RELEASE = 0
KEY_PRESS = 1
KEY_REPEAT = 2
KEY_BITS = frozenset((KEY_VOLUMEDOWN, KEY_VOLUMEUP))

# KEY_CNT (0x300) rounded up to whole bytes.
KEY_BITS_LENGTH = 96
INPUT_EVENT = struct.Struct("@llHHi")
INPUT_EVENT_SIZE = INPUT_EVENT.size

TERMINAL_STATES = frozenset(("authorized", "cancelled", "timeout"))
EXIT_CODES = {"authorized": 0, "cancelled": 2, "timeout": 3}

# The kernel decodes EVIOCGRAB's integer argument directly, not through a
# pointer, so passing the value as an int is correct.
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction, type_, number, size):
    return ((direction << _IOC_DIRSHIFT) | (type_ << _IOC_TYPESHIFT)
            | (size << _IOC_SIZESHIFT) | (number << _IOC_NRSHIFT))


def eviocgbit(ev_type, length):
    return _ioc(_IOC_READ, ord("E"), 0x20 + ev_type, length)


def eviocgkey(length):
    return _ioc(_IOC_READ, ord("E"), 0x18, length)


def eviocgname(length):
    return _ioc(_IOC_READ, ord("E"), 0x06, length)


def eviocgrab():
    return _ioc(_IOC_WRITE, ord("E"), 0x90, struct.calcsize("i"))


def decode_key_bitmap(data):
    return {code for code in range(len(data) * 8)
            if data[code // 8] & (1 << (code % 8))}


def read_key_capabilities(fd):
    buffer = bytearray(KEY_BITS_LENGTH)
    fcntl.ioctl(fd, eviocgbit(EV_KEY, len(buffer)), buffer)
    return decode_key_bitmap(bytes(buffer))


def held_keys(fd):
    buffer = bytearray(KEY_BITS_LENGTH)
    fcntl.ioctl(fd, eviocgkey(len(buffer)), buffer)
    return decode_key_bitmap(bytes(buffer))


def read_device_name(fd):
    buffer = bytearray(256)
    try:
        fcntl.ioctl(fd, eviocgname(len(buffer)), buffer)
    except OSError:
        return ""
    return bytes(buffer).split(b"\x00", 1)[0].decode("utf-8", "replace")


def set_grab(fd, grab=True):
    fcntl.ioctl(fd, eviocgrab(), 1 if grab else 0)


class InputEvent:
    __slots__ = ("type", "code", "value")

    def __init__(self, type_, code, value):
        self.type = type_
        self.code = code
        self.value = value

    def __eq__(self, other):
        return (isinstance(other, InputEvent) and self.type == other.type
                and self.code == other.code and self.value == other.value)

    def __repr__(self):
        return f"InputEvent(type={self.type}, code={self.code}, value={self.value})"


# A distinct marker rather than an InputEvent: SYN_DROPPED means every pending
# gesture is untrustworthy and the caller must resync from EVIOCGKEY.
SYN_DROPPED = object()


def parse_events(buffer):
    events = []
    offset = 0
    while offset + INPUT_EVENT_SIZE <= len(buffer):
        _, _, type_, code, value = INPUT_EVENT.unpack_from(buffer, offset)
        offset += INPUT_EVENT_SIZE
        if type_ == EV_SYN and code == SYN_DROPPED_CODE:
            events.append(SYN_DROPPED)
        else:
            events.append(InputEvent(type_, code, value))
    return events, buffer[offset:]


class Device:
    __slots__ = ("path", "fd", "name", "keys")

    def __init__(self, path, fd, name, keys):
        self.path = str(path)
        self.fd = fd
        self.name = name
        self.keys = keys


def open_capable(paths, required=KEY_BITS):
    """Open evdev devices that advertise at least one required key."""
    devices = []
    for path in paths:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            keys = read_key_capabilities(fd)
        except OSError:
            os.close(fd)
            continue
        if not (required & keys):
            os.close(fd)
            continue
        devices.append(Device(path, fd, read_device_name(fd), keys))
    return devices


class DeviceDisconnected(Exception):
    pass


class EventReader:
    __slots__ = ("fd", "path", "buffer")

    def __init__(self, fd, path=""):
        self.fd = fd
        self.path = path
        self.buffer = b""

    def read(self):
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return []
        if not data:
            raise DeviceDisconnected(self.path)
        self.buffer += data
        events, self.buffer = parse_events(self.buffer)
        return events


class Gate:
    """Event-driven readiness state machine, independent of file descriptors."""

    def __init__(self, settle=3.0, on_state=None, clock=time.monotonic):
        self.settle = float(settle)
        self.clock = clock
        self.on_state = on_state or (lambda state, detail: None)
        self.state = "discovering"
        self.detail = "start"
        self.settle_deadline = None
        self._held = set()
        self._pressed = set()

    def _transition(self, state, detail=""):
        if state != self.state or detail != self.detail:
            self.state = state
            self.detail = detail
            self.on_state(state, detail)

    def resync(self, current_held):
        if self.state not in ("discovering", "waiting"):
            return
        self._held = set(current_held) & KEY_BITS
        self._pressed = set()
        self._transition("waiting", "awaiting-volume-up")

    def disconnected(self):
        if self.state == "settling":
            self._transition("cancelled", "input-disconnected")
        elif self.state in ("discovering", "waiting"):
            self._transition("waiting", "input-disconnected")

    def expire(self):
        if self.state in ("discovering", "waiting"):
            self._transition("timeout", "no-fresh-volume-up")

    def feed(self, event):
        if (event is SYN_DROPPED
                or (isinstance(event, InputEvent) and event.type == EV_SYN
                    and event.code == SYN_DROPPED_CODE)):
            # Drop any partial gesture. The caller resyncs from EVIOCGKEY; this
            # path must never authorize a capture.
            self._pressed.clear()
            if self.state == "settling":
                self._transition("cancelled", "syn-dropped")
            return self.state
        if (not isinstance(event, InputEvent) or event.type != EV_KEY
                or event.code not in KEY_BITS or event.value == KEY_REPEAT):
            return self.state
        code, value = event.code, event.value
        if value == KEY_PRESS:
            if code in self._held:
                return self.state
            self._pressed.add(code)
            if code == KEY_VOLUMEDOWN:
                self._transition("cancelled", "volume-down")
            return self.state
        if value == KEY_RELEASE:
            if code in self._held:
                # Release of a key that was already down at discovery.
                self._held.discard(code)
                self._pressed.discard(code)
                return self.state
            if code not in self._pressed:
                return self.state
            self._pressed.discard(code)
            if code == KEY_VOLUMEUP and self.state in ("discovering", "waiting"):
                self.settle_deadline = self.clock() + self.settle
                self._transition("settling", f"hold-still-{self.settle:g}s")
        return self.state

    def tick(self, now=None):
        if self.state == "settling" and self.settle_deadline is not None:
            now = self.clock() if now is None else now
            if now >= self.settle_deadline:
                self._transition("authorized", "volume-up-release-confirmed")
        return self.state


INSTRUCTIONS = {
    "discovering": "Looking for a volume-key input device.",
    "waiting": ("Phone is face-down. Pick it up, aim the rear camera at the "
                "target, then press Volume Up. Volume Down cancels."),
    "settling": "Authorized. Hold still now; the capture starts shortly. Volume Down cancels.",
    "authorized": "Readiness confirmed.",
    "cancelled": "Cancelled or input lost; no capture was run.",
    "timeout": "No fresh Volume Up within the timeout; no capture was run.",
    "capturing": "Running the single capture command.",
    "capture-failed": "Capture command failed or left live processes.",
    "complete": "Single capture completed.",
}


class Reporter:
    def __init__(self, stream, status_file=None, notify=None, quiet=False):
        self.stream = stream
        self.status_file = Path(status_file) if status_file else None
        self.notify = notify
        self.quiet = quiet

    @staticmethod
    def _clean(text, limit=200):
        return " ".join(str(text).split())[:limit]

    def state(self, state, detail=""):
        detail = self._clean(detail)
        instruction = INSTRUCTIONS.get(state, "")
        parts = [f"{PREFIX}: state={state}"]
        if detail:
            parts.append(f'detail="{detail}"')
        if instruction and not self.quiet:
            parts.append(f'instruct="{instruction}"')
        line = " ".join(parts)
        print(line, file=self.stream, flush=True)
        self._publish(line, state, detail)

    def warn(self, message):
        print(f'{PREFIX}: warn="{self._clean(message)}"', file=self.stream, flush=True)

    def _publish(self, line, state, detail):
        if self.status_file is not None:
            try:
                self._write_status(line)
            except OSError:
                pass
        if self.notify:
            try:
                subprocess.run([self.notify, state, detail], timeout=2,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass

    def _write_status(self, line):
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_name(self.status_file.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, (line + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        os.replace(temporary, self.status_file)


def group_members(group):
    """Return live members of a process group, excluding zombies."""
    members = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ESRCH):
                continue
            raise
        if int(fields[2]) == group and fields[0] not in {"Z", "X"}:
            members.append(int(path.parent.name))
    return members


def _signal_group(group, signum):
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def _terminate_group(group, grace=1.0):
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not group_members(group):
            break
        _signal_group(group, signum)
        deadline = time.monotonic() + grace
        while group_members(group) and time.monotonic() < deadline:
            time.sleep(0.05)


def run_capture(command, timeout, log=None):
    """Run the one authorized command; always reap its private process group."""
    result = {"timed_out": False, "returncode": None, "remaining_processes": []}
    stream = subprocess.DEVNULL
    if log:
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        stream = os.fdopen(descriptor, "w")
    process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        try:
            result["returncode"] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            _signal_group(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    finally:
        _terminate_group(process.pid)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        result["remaining_processes"] = group_members(process.pid)
        if log:
            stream.close()
    return result


def wait_for_readiness(readers, gate, timeout, reporter, *, command=None,
                       capture_timeout=30, log=None, grab=False,
                       select_fn=select.select, clock=time.monotonic,
                       sleep_fn=time.sleep, capture=run_capture):
    grabbed = []
    opened = list(readers)
    try:
        if grab:
            for reader in readers:
                try:
                    set_grab(reader.fd, True)
                except OSError as error:
                    reporter.warn(f"exclusive-grab-unavailable {reader.path}: "
                                  f"{error.strerror or error}")
                else:
                    grabbed.append(reader.fd)
        deadline = clock() + timeout
        while gate.state not in TERMINAL_STATES:
            now = clock()
            if gate.state in ("discovering", "waiting"):
                if now >= deadline:
                    gate.expire()
                    break
                wait = deadline - now
            else:
                wait = None
            if gate.state == "settling":
                remaining = (None if gate.settle_deadline is None
                             else gate.settle_deadline - now)
                if remaining is not None and remaining <= 0:
                    gate.tick(now)
                    continue
                wait = remaining if wait is None else min(wait, remaining)
            fds = [reader.fd for reader in opened]
            if not fds:
                sleep_fn(min(0.2, wait if wait else 0.2))
                gate.tick(clock())
                continue
            try:
                ready, _, _ = select_fn(fds, [], [], wait)
            except InterruptedError:
                continue
            if not ready:
                gate.tick(clock())
                continue
            for reader in list(opened):
                if reader.fd not in ready:
                    continue
                try:
                    events = reader.read()
                except DeviceDisconnected:
                    reporter.warn(f"disconnected {reader.path}")
                    opened.remove(reader)
                    gate.disconnected()
                    continue
                except OSError as error:
                    if error.errno not in (errno.ENODEV, errno.EIO, errno.ENXIO):
                        raise
                    reporter.warn(f"disconnected {reader.path}: "
                                  f"{error.strerror or error}")
                    opened.remove(reader)
                    gate.disconnected()
                    continue
                for event in events:
                    gate.feed(event)
                    if event is SYN_DROPPED and gate.state in ("discovering", "waiting"):
                        try:
                            gate.resync(held_keys(reader.fd))
                        except OSError:
                            pass
                gate.tick(clock())
            if gate.state == "authorized":
                break
        if gate.state == "authorized" and command:
            reporter.state("capturing", "single-capture-command")
            result = capture(command, capture_timeout, log)
            if result["timed_out"]:
                reporter.state("capture-failed", "timeout")
                return 4
            if result["remaining_processes"]:
                reporter.state("capture-failed", "left-live-processes")
                return 4
            if result["returncode"] != 0:
                reporter.state("capture-failed", f"exit-{result['returncode']}")
                return 4
            reporter.state("complete", "capture-finished")
        return EXIT_CODES.get(gate.state, 4)
    finally:
        for fd in grabbed:
            try:
                set_grab(fd, False)
            except OSError:
                reporter.warn("exclusive-grab-release-failed")


def initial_held(devices):
    held = set()
    for device in devices:
        try:
            held |= held_keys(device.fd)
        except OSError:
            pass
    return held


def normalize_command(command):
    """Drop the leading `--` that argparse.REMAINDER keeps for a positional."""
    command = list(command or [])
    if command and command[0] == "--":
        command = command[1:]
    return command or None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dev-root", default="/dev/input",
                        help="directory containing event* nodes (default /dev/input)")
    parser.add_argument("--timeout", type=float, default=120.0,
                        help="seconds to wait for a fresh Volume Up (1..3600)")
    parser.add_argument("--settle", type=float, default=3.0,
                        help="hold-still seconds after Volume Up release (0..60)")
    parser.add_argument("--capture-timeout", type=float, default=30.0,
                        help="seconds allowed for the capture command (1..600)")
    parser.add_argument("--grab", action="store_true",
                        help="attempt EVIOCGRAB on capable devices (default off)")
    parser.add_argument("--status-file", type=Path,
                        help="optionally mirror the latest state to this private file")
    parser.add_argument("--notify", help="optional existing-UI cue program called with state detail")
    parser.add_argument("--log", type=Path, help="private log file for the capture command")
    parser.add_argument("--quiet", action="store_true", help="omit instruction text")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="single capture command after -- (Megapixels/libcamera wrapper)")
    args = parser.parse_args(argv)
    if not 0 <= args.settle <= 60:
        parser.error("--settle must be 0..60")
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be 1..3600")
    if not 1 <= args.capture_timeout <= 600:
        parser.error("--capture-timeout must be 1..600")
    os.umask(0o077)
    reporter = Reporter(sys.stdout, status_file=args.status_file,
                        notify=args.notify, quiet=args.quiet)
    reporter.state("discovering", f"dev-root={args.dev_root}")
    paths = sorted(Path(args.dev_root).glob("event*"))
    devices = open_capable(paths)
    reporter.warn(f"capable-devices={len(devices)}")
    gate = Gate(settle=args.settle, on_state=reporter.state)
    gate.resync(initial_held(devices))
    readers = [EventReader(device.fd, device.path) for device in devices]
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        return wait_for_readiness(
            readers, gate, args.timeout, reporter,
            command=normalize_command(args.command),
            capture_timeout=args.capture_timeout,
            log=str(args.log) if args.log else None, grab=args.grab)
    except KeyboardInterrupt:
        reporter.state("cancelled", "interrupted")
        return 130
    finally:
        for device in devices:
            try:
                os.close(device.fd)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
