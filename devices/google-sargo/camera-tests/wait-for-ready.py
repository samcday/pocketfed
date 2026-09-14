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

While the authorized capture runs, input is still monitored: a Volume Down or
an input disconnect cancels and the owned capture process group is cleaned up.
Key gestures are matched per device, so a press on one node and a release on
another cannot authorize a capture.

Integration contract, one line per transition on stdout (also serial/log):

    pocketfed-camera-readiness: state=<state> detail="<detail>" instruct="<text>"

States: discovering, waiting, settling, authorized, cancelled, timeout,
capturing, capture-failed, complete. Cancellation details end in
`before-capture` or `during-capture` so the outcome is unambiguous. An optional
private status file and an optional existing-UI notify hook mirror the same
state. See readiness.md.

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
SYN_REPORT_CODE = 0
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


# Distinct markers rather than InputEvent values. SYN_DROPPED means pending
# state is untrustworthy; RESYNC means the drop interval ended at SYN_REPORT and
# the device must be re-queried with EVIOCGKEY.
SYN_DROPPED = object()
RESYNC = object()


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


def probe_initial_state(devices):
    """Split devices whose current key state could be read from unknown ones.

    A device whose EVIOCGKEY fails has unknown state and must be excluded: an
    already-held key could otherwise be mistaken for a fresh gesture.
    """
    held_by_device = {}
    usable = []
    unknown = []
    for device in devices:
        try:
            held_by_device[device.path] = held_keys(device.fd)
        except OSError:
            unknown.append(device)
            continue
        usable.append(device)
    return held_by_device, usable, unknown


class DeviceDisconnected(Exception):
    pass


class EventReader:
    __slots__ = ("fd", "path", "buffer", "dropping")

    def __init__(self, fd, path=""):
        self.fd = fd
        self.path = path
        self.buffer = b""
        # After SYN_DROPPED the kernel may still deliver stale events from the
        # lost interval; ignore them all until the boundary SYN_REPORT.
        self.dropping = False

    def read(self):
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return []
        if not data:
            raise DeviceDisconnected(self.path)
        self.buffer += data
        parsed, self.buffer = parse_events(self.buffer)
        events = []
        for event in parsed:
            if event is SYN_DROPPED:
                self.dropping = True
                events.append(SYN_DROPPED)
                continue
            if self.dropping:
                if (isinstance(event, InputEvent) and event.type == EV_SYN
                        and event.code == SYN_REPORT_CODE):
                    self.dropping = False
                    events.append(RESYNC)
                continue
            events.append(event)
        return events


class Gate:
    """Event-driven readiness state machine, independent of file descriptors.

    Gestures are tracked per (device, key) so multiple nodes that advertise
    Volume Up cannot be mixed into one press/release pair.
    """

    def __init__(self, settle=3.0, on_state=None, clock=time.monotonic):
        self.settle = float(settle)
        self.clock = clock
        self.on_state = on_state or (lambda state, detail: None)
        self.state = "discovering"
        self.detail = "start"
        self.settle_deadline = None
        self.capture_started = False
        self._held = set()
        self._pressed = set()

    def _transition(self, state, detail=""):
        if state != self.state or detail != self.detail:
            self.state = state
            self.detail = detail
            self.on_state(state, detail)

    def _cancel(self, reason):
        phase = "during-capture" if self.capture_started else "before-capture"
        self._transition("cancelled", f"{reason}-{phase}")

    def resync(self, held_by_device):
        if self.state not in ("discovering", "waiting"):
            return
        mapping = (held_by_device if isinstance(held_by_device, dict)
                   else {None: held_by_device})
        self._held = {(device, code) for device, codes in mapping.items()
                      for code in codes if code in KEY_BITS}
        self._pressed = set()
        self._transition("waiting", "awaiting-volume-up")

    def resync_device(self, device, held_codes):
        if self.state not in ("discovering", "waiting"):
            return
        self._held = {entry for entry in self._held if entry[0] != device}
        self._pressed = {entry for entry in self._pressed if entry[0] != device}
        self._held |= {(device, code) for code in held_codes if code in KEY_BITS}

    def disconnected(self):
        if self.state in ("settling", "authorized"):
            self._cancel("input-disconnected")
        elif self.state in ("discovering", "waiting"):
            self._transition("waiting", "input-disconnected")

    def fail_closed(self, reason):
        self._cancel(reason)

    def expire(self):
        if self.state in ("discovering", "waiting"):
            self._transition("timeout", "no-fresh-volume-up")

    def feed(self, event, device=None):
        if (event is SYN_DROPPED
                or (isinstance(event, InputEvent) and event.type == EV_SYN
                    and event.code == SYN_DROPPED_CODE)):
            # Drop any partial gesture. The caller re-queries EVIOCGKEY at the
            # next SYN_REPORT; this path must never authorize a capture.
            self._pressed.clear()
            if self.state in ("settling", "authorized"):
                self._cancel("syn-dropped")
            return self.state
        if (not isinstance(event, InputEvent) or event.type != EV_KEY
                or event.code not in KEY_BITS or event.value == KEY_REPEAT):
            return self.state
        identity = (device, event.code)
        if event.value == KEY_PRESS:
            if identity in self._held:
                return self.state
            self._pressed.add(identity)
            if event.code == KEY_VOLUMEDOWN:
                self._cancel("volume-down")
            return self.state
        if event.value == KEY_RELEASE:
            if identity in self._held:
                # Release of a key that was already down at discovery.
                self._held.discard(identity)
                self._pressed.discard(identity)
                return self.state
            if identity not in self._pressed:
                return self.state
            self._pressed.discard(identity)
            if event.code == KEY_VOLUMEUP and self.state in ("discovering", "waiting"):
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
    "cancelled": "Cancelled or input lost; the owned capture was stopped. No new capture.",
    "timeout": "No fresh Volume Up within the timeout; no capture was run.",
    "capturing": "Running the single capture command; Volume Down still cancels.",
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


class Capture:
    """Own exactly one capture process group so cleanup stays scoped."""

    def __init__(self, command, timeout, log=None):
        self.command = command
        self.timeout = timeout
        self.log = log
        self.process = None
        self.deadline = None
        self._stream = None
        self._close_stream = False

    def start(self, clock=time.monotonic):
        stream = subprocess.DEVNULL
        if self.log:
            descriptor = os.open(self.log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            stream = os.fdopen(descriptor, "w")
            self._close_stream = True
        self._stream = stream
        self.process = subprocess.Popen(self.command, stdout=stream,
                                        stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL,
                                        start_new_session=True)
        self.deadline = clock() + self.timeout
        return self

    def poll(self):
        return None if self.process is None else self.process.poll()

    def expired(self, now):
        return self.deadline is not None and now >= self.deadline

    def _close(self):
        if self._close_stream and self._stream is not None:
            self._stream.close()
            self._close_stream = False

    def reap(self):
        """Reap a finished capture and clean any helpers it left behind."""
        if self.process is None:
            return None, []
        try:
            returncode = self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            returncode = None
        _terminate_group(self.process.pid)
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        remaining = group_members(self.process.pid)
        self._close()
        self.process = None
        return returncode, remaining

    def stop(self):
        """Stop a running capture group, SIGINT first for libcamera's benefit."""
        if self.process is None:
            return []
        _signal_group(self.process.pid, signal.SIGINT)
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        _terminate_group(self.process.pid)
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        remaining = group_members(self.process.pid)
        self._close()
        self.process = None
        return remaining


def run_capture(command, timeout, log=None):
    """Blocking one-shot capture, kept for standalone and test use."""
    capture = Capture(command, timeout, log).start()
    result = {"timed_out": False, "returncode": None, "remaining_processes": []}
    try:
        result["returncode"] = capture.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        result["remaining_processes"] = capture.stop()
        return result
    _, remaining = capture.reap()
    result["remaining_processes"] = remaining
    return result


def read_ready(opened, ready, gate, reporter):
    """Read and feed events from ready devices, handling disconnect and resync."""
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
            reporter.warn(f"disconnected {reader.path}: {error.strerror or error}")
            opened.remove(reader)
            gate.disconnected()
            continue
        for event in events:
            if event is RESYNC:
                try:
                    held = held_keys(reader.fd)
                except OSError as error:
                    # Unknown state must fail closed, not look like no keys held.
                    reporter.warn(f"resync-failed {reader.path}: "
                                  f"{error.strerror or error}")
                    gate.fail_closed("resync-failed")
                    continue
                gate.resync_device(reader.path, held)
                continue
            gate.feed(event, reader.path)


def wait_for_readiness(readers, gate, timeout, reporter, *, command=None,
                       capture_timeout=30, log=None, grab=False,
                       select_fn=select.select, clock=time.monotonic,
                       sleep_fn=time.sleep, capture_factory=Capture):
    grabbed = []
    opened = list(readers)
    session = None
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
        while True:
            now = clock()
            # Monitor the owned capture first so a capture that already exited
            # is reported as complete rather than as a late cancellation.
            if session is not None:
                returncode = session.poll()
                if returncode is not None:
                    _, remaining = session.reap()
                    if remaining:
                        reporter.state("capture-failed", "left-live-processes")
                        return 4
                    if returncode != 0:
                        reporter.state("capture-failed", f"exit-{returncode}")
                        return 4
                    reporter.state("complete", "capture-finished")
                    return 0
                if session.expired(now):
                    session.stop()
                    reporter.state("capture-failed", "timeout")
                    return 4
            if gate.state == "cancelled":
                if session is not None:
                    session.stop()
                return 2
            if gate.state == "timeout":
                return 3
            if gate.state == "authorized":
                if not command:
                    return 0
                if not gate.capture_started:
                    reporter.state("capturing", "single-capture-command")
                    session = capture_factory(command, capture_timeout, log)
                    session.start(clock)
                    gate.capture_started = True
                    continue
            # Compute the wait bound; keep polling quickly while capturing.
            if gate.state in ("discovering", "waiting"):
                if now >= deadline:
                    gate.expire()
                    return 3
                wait = deadline - now
            elif gate.state == "settling":
                wait = (None if gate.settle_deadline is None
                        else gate.settle_deadline - now)
            else:
                wait = None
            if session is not None:
                wait = 0.2 if wait is None else min(wait, 0.2)
            if wait is not None and wait < 0:
                wait = 0
            fds = [reader.fd for reader in opened]
            if not fds:
                delay = (0.1 if session is not None
                         else 0.2 if wait is None else min(0.2, wait))
                sleep_fn(delay)
                gate.tick(clock())
                continue
            try:
                ready, _, _ = select_fn(fds, [], [], wait)
            except InterruptedError:
                ready = []
            if ready:
                read_ready(opened, ready, gate, reporter)
            # At countdown expiry, drain anything already pending so a
            # cancellation or input loss cannot be missed before capture starts.
            if gate.state == "settling":
                try:
                    pending, _, _ = select_fn(fds, [], [], 0)
                except InterruptedError:
                    pending = []
                if pending:
                    read_ready(opened, pending, gate, reporter)
            gate.tick(clock())
    finally:
        if session is not None:
            session.stop()
        for fd in grabbed:
            try:
                set_grab(fd, False)
            except OSError:
                reporter.warn("exclusive-grab-release-failed")


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
                        help="single capture command after -- (capture wrapper)")
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
    opened_devices = open_capable(paths)
    reporter.warn(f"capable-devices={len(opened_devices)}")
    held_by_device, usable, unknown = probe_initial_state(opened_devices)
    for device in unknown:
        reporter.warn(f"initial-state-unknown {device.path}: excluded from authorization")
    gate = Gate(settle=args.settle, on_state=reporter.state)
    gate.resync(held_by_device)
    readers = [EventReader(device.fd, device.path) for device in usable]
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        return wait_for_readiness(
            readers, gate, args.timeout, reporter,
            command=normalize_command(args.command),
            capture_timeout=args.capture_timeout,
            log=str(args.log) if args.log else None, grab=args.grab)
    except KeyboardInterrupt:
        reporter.state("cancelled", "interrupted-before-capture")
        return 130
    finally:
        for device in opened_devices:
            try:
                os.close(device.fd)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
