#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Switch the lab USB relay module and hard power-cycle boards wired through it.

"on" always means the relay coil is energised: NO closes and NC opens. A load
wired through COM and NC stays powered while its channel is off, including
when the host is down or the module is unplugged. See README.md.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import select
import signal
import stat
import sys
import termios
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROG = "relay.py"
CONFIG = Path(__file__).resolve().with_name("relay.toml")

EXIT_OK = 0
EXIT_ERROR = 1        # bad arguments or configuration, relay I/O failure, interrupted
EXIT_BUSY = 2         # refused: another process is using the board or the relay
EXIT_NO_RELAY = 3     # relay module missing, unsupported or not accessible
EXIT_NO_FASTBOOT = 4  # the console showed a boot but fastboot never appeared
EXIT_NO_SIGN = 5      # neither console output nor fastboot after power returned
EXIT_NOT_CUT = 6      # the board stayed on USB while its power should have been off

# Console milestones after power returns: Qualcomm SBL1, the U-Boot banner and
# U-Boot's autoboot countdown, which ends in its resident fastboot.
MARKERS = {
    "sbl1": re.compile(rb"SBL1, Start"),
    "u-boot": re.compile(rb"U-Boot 20\d\d\.\d\d[^\r\n]*(?=[\r\n])"),
    "autoboot": re.compile(rb"Hit any key to stop autoboot"),
}
# Host tools that act on a board over USB; see board_users().
BOARD_TOOLS = {"fastboot", "fastboop", "pocketfed-liveboot"}


class Failure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def progress(message):
    print(message, file=sys.stderr, flush=True)


@dataclass
class Channel:
    number: int
    name: str = ""
    wiring: str = ""  # contact that carries the load: "NC" or "NO"
    target: str = ""

    def __str__(self):
        return f"channel {self.number}" + (f" ({self.name})" if self.name else "")

    def coil_for(self, powered):
        """Coil state that leaves the load powered or unpowered."""
        return powered == (self.wiring == "NO")

    def load(self, coil):
        if not self.wiring:
            return ""
        powered = coil == (self.wiring == "NO")
        return f"{self.target or 'load'} {'powered' if powered else 'UNPOWERED'} ({self.wiring})"


@dataclass
class Target:
    name: str
    channel: Channel
    fastboot_serial: str
    smoo_usb: tuple
    uart: str
    off_seconds: float
    timeout: float


@dataclass
class Config:
    device: str
    channels: dict
    targets: dict

    def channel(self, key):
        for channel in self.channels.values():
            if key in (str(channel.number), channel.name):
                return channel
        names = ", ".join(str(c.number) + (f"={c.name}" if c.name else "")
                          for c in self.channels.values())
        raise Failure(EXIT_ERROR, f"no channel {key!r}; channels: {names}")


def load_config(path):
    try:
        with open(path, "rb") as file:
            raw = tomllib.load(file)
        relay = raw.get("relay", {})
        channels = {n: Channel(n) for n in range(1, int(relay.get("channels", 4)) + 1)}
        for key, spec in raw.get("channel", {}).items():
            channel = Channel(int(key), spec.get("name", ""), spec.get("wiring", "").upper(),
                              spec.get("target", ""))
            if channel.number not in channels or channel.wiring not in ("", "NC", "NO"):
                raise ValueError(f"channel {key}: unknown number or wiring")
            channels[channel.number] = channel
        targets = {}
        for name, spec in raw.get("target", {}).items():
            wired = [c for c in channels.values() if c.target == name and c.wiring]
            if len(wired) != 1:
                raise ValueError(f"target {name} needs exactly one channel with wiring")
            vid, pid = spec["smoo_usb"].lower().split(":")
            targets[name] = Target(name, wired[0], spec["fastboot_serial"], (vid, pid),
                                   spec["uart"], float(spec.get("off_seconds", 5)),
                                   float(spec.get("timeout", 60)))
        for channel in channels.values():
            if channel.target and channel.target not in targets:
                raise ValueError(f"{channel} names undefined target {channel.target}")
    except (OSError, tomllib.TOMLDecodeError, KeyError, ValueError) as error:
        raise Failure(EXIT_ERROR, f"config {path}: {error}")
    return Config(relay.get("device", "/dev/lab-relay"), channels, targets)


def hidioc(nr, size):
    """_IOC(_IOC_READ | _IOC_WRITE, 'H', nr, size) from linux/hidraw.h."""
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


def dcttech_report(channel, on):
    """Feature report 0: FF (on) or FD (off), then the 1-based channel."""
    return bytearray((0, 0xFF if on else 0xFD, channel, 0, 0, 0, 0, 0, 0))


def dcttech_states(report):
    """Byte 7 of the report data is the energised-coil bitmask, bit 0 = channel 1."""
    return {n: bool(report[8] >> (n - 1) & 1) for n in range(1, 9)}


def configure_tty(fd, speed):
    """Raw 8N1 with no modem control and non-blocking reads."""
    attrs = termios.tcgetattr(fd)
    attrs[0:4] = [0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0]
    attrs[4] = attrs[5] = speed
    attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def read_available(fd, timeout):
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return b""
    try:
        return os.read(fd, 4096)
    except BlockingIOError:
        return b""


class DcttechHid:
    """V-USB "USBRelayN" boards (16c0:05df, www.dcttech.com), via hidraw feature reports."""

    def __init__(self, fd):
        self.fd = fd
        self.serial = ""  # the board's own 5-character ID; USB has no serial string

    def set(self, channel, on):
        report = dcttech_report(channel, on)
        fcntl.ioctl(self.fd, hidioc(0x06, len(report)), report)  # HIDIOCSFEATURE

    def read(self):
        report = bytearray(9)
        if fcntl.ioctl(self.fd, hidioc(0x07, len(report)), report) < len(report):  # HIDIOCGFEATURE
            raise Failure(EXIT_ERROR, "short feature report from the relay module")
        self.serial = report[1:6].decode("ascii", "replace")
        return dcttech_states(report)


@dataclass
class Node:
    """A character device and the USB device it belongs to."""

    dev: str
    subsystem: str
    usb: Path
    id_path: str

    def attr(self, name):
        try:
            return (self.usb / name).read_text().strip()
        except OSError:
            return ""

    @property
    def vid_pid(self):
        return self.attr("idVendor"), self.attr("idProduct")

    @property
    def supported(self):
        return ((self.subsystem, *self.vid_pid) == ("hidraw", "16c0", "05df")
                and self.attr("product").startswith("USBRelay"))

    def __str__(self):
        return (f"{self.dev}  {':'.join(self.vid_pid)} {self.attr('manufacturer')} "
                f"{self.attr('product')}  {self.id_path or 'no ID_PATH'}")


def node_info(path):
    try:
        dev = os.path.realpath(path)
        rdev = os.stat(dev)
        if not stat.S_ISCHR(rdev.st_mode):
            return None
        major, minor = os.major(rdev.st_rdev), os.minor(rdev.st_rdev)
        sysfs = Path(f"/sys/dev/char/{major}:{minor}").resolve()
        subsystem = (sysfs / "subsystem").resolve().name
    except OSError:
        return None
    try:
        udev = Path(f"/run/udev/data/c{major}:{minor}").read_text()
    except OSError:
        udev = ""
    usb = next((p for p in (sysfs, *sysfs.parents) if (p / "idVendor").exists()), None)
    id_path = re.search(r"^E:ID_PATH=(.*)$", udev, re.MULTILINE)
    return usb and Node(dev, subsystem, usb, id_path.group(1) if id_path else "")


def candidates():
    nodes = (node_info(dev) for dev in sorted(Path("/dev").glob("hidraw*")))
    return [node for node in nodes if node and node.supported]


def holders(dev):
    return [f"pid {pid} ({os.path.basename(argv[0])})"
            for pid, argv in processes() if holds(pid, dev)]


def open_relay(config, device=None):
    path = device or config.device
    node = node_info(path)
    if node is None or not node.supported:
        raise Failure(EXIT_NO_RELAY, f"{path} is missing or not a supported relay module;"
                      f" run `{PROG} identify` (README.md has the udev setup)")
    try:
        fd = os.open(node.dev, os.O_RDWR | os.O_CLOEXEC)
    except OSError as error:
        raise Failure(EXIT_NO_RELAY, f"cannot open {node.dev}: {error.strerror}"
                      " (is the udev rule installed?)")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        users = ", ".join(holders(node.dev)) or "another process"
        raise Failure(EXIT_BUSY, f"relay {node.dev} is locked by {users}")
    return node, DcttechHid(fd)


def switch(relay, channel, coil):
    """Switch a coil and check the module's own report of it."""
    relay.set(channel.number, coil)
    if relay.read()[channel.number] != coil:
        raise Failure(EXIT_ERROR, f"{channel}: module still reports the coil "
                      f"{'off' if coil else 'on'}")


def restore(relay, channel, coil, what):
    """Switch a coil back with signals held, so an interrupt cannot strand it."""
    held = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM, signal.SIGHUP))
    try:
        switch(relay, channel, coil)
    except (OSError, Failure) as error:
        raise Failure(EXIT_ERROR, f"{what} NOT RESTORED: {error}; run"
                      f" `{PROG} {'on' if coil else 'off'} {channel.number}`")
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, held)


def ancestors():
    pids, pid = set(), os.getpid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            break
        pid = int(re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE).group(1))
    return pids


def processes():
    """(pid, argv) of readable processes, except this one and the shells that started it."""
    skip = ancestors()
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit() or int(entry.name) in skip:
            continue
        try:
            raw = Path(entry.path, "cmdline").read_bytes()
        except OSError:
            continue
        argv = [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]
        if argv:
            yield int(entry.name), argv


def holds(pid, dev):
    try:
        fds = list(os.scandir(f"/proc/{pid}/fd"))
    except OSError:
        return False
    for fd in fds:
        try:
            if os.readlink(fd.path) == dev:
                return True
        except OSError:
            pass
    return False


def smoo_product(argv):
    for arg, value in zip(argv, argv[1:] + [""]):
        if arg.startswith("--product-id="):
            arg, value = arg.split("=", 1)
        if arg == "--product-id":
            try:
                return int(value, 0)
            except ValueError:
                return None
    return None


def usb_devices():
    for dev in Path("/sys/bus/usb/devices").iterdir():
        if ":" in dev.name:
            continue
        attrs = {}
        for key in ("idVendor", "idProduct", "serial"):
            try:
                attrs[key] = (dev / key).read_text().strip()
            except OSError:
                attrs[key] = ""
        yield dev, attrs


def is_fastboot(dev):
    for interface in dev.glob(f"{dev.name}:*"):
        try:
            triple = [(interface / name).read_text().strip()
                      for name in ("bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol")]
        except OSError:
            continue
        if triple == ["ff", "42", "03"]:
            return True
    return False


def board_on_usb(target):
    """How the target shows up on USB right now: "fastboot", "smoo" or None."""
    for dev, attrs in usb_devices():
        if attrs["serial"] == target.fastboot_serial and is_fastboot(dev):
            return "fastboot"
        if (attrs["idVendor"], attrs["idProduct"]) == target.smoo_usb:
            return "smoo"
    return None


def board_users(target):
    """Evidence that another session is using the target right now."""
    uart = os.path.realpath(target.uart)
    smoo_pid = int(target.smoo_usb[1], 16)
    reasons = []
    for pid, argv in processes():
        name = os.path.basename(argv[0])
        if holds(pid, uart):
            reasons.append(f"pid {pid} ({name}) has the console {target.uart} open")
        elif name == "smoo-host" and smoo_product(argv) == smoo_pid:
            reasons.append(f"pid {pid} smoo-host serves {target.name}: {' '.join(argv)}")
        elif name in BOARD_TOOLS and (any(target.fastboot_serial in arg for arg in argv)
                                      or (name == "fastboot" and "-s" not in argv)):
            reasons.append(f"pid {pid} may be using {target.name}: {' '.join(argv)}")
    if board_on_usb(target) == "smoo":
        reasons.append(f"{target.name} is on USB as the smoo gadget"
                       f" {':'.join(target.smoo_usb)}: a liveboot is running")
    return reasons


def refuse_if_busy(target):
    reasons = board_users(target)
    if reasons:
        raise Failure(EXIT_BUSY, f"{target.name} looks in use, leaving its power alone"
                      " (--force if it is yours):\n  " + "\n  ".join(reasons))


def guard(config, channel, coil, force):
    """Run the busy check before any switch that would leave a target unpowered."""
    if channel.target and coil == channel.coil_for(False) and not force:
        refuse_if_busy(config.targets[channel.target])


def open_console(target, force):
    """Open the target's UART read-only and exclusively; (fd or None, note)."""
    try:
        fd = os.open(target.uart, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None, f"not watched: {target.uart} is missing"
    except OSError as error:
        if force:
            return None, f"not watched: {error.strerror}"
        raise Failure(EXIT_BUSY, f"console {target.uart}: {error.strerror} (--force to skip it)")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        configure_tty(fd, termios.B115200)
        termios.tcflush(fd, termios.TCIFLUSH)
    except BlockingIOError:
        os.close(fd)
        if force:
            return None, "not watched: locked by another process"
        raise Failure(EXIT_BUSY, f"console {target.uart} is locked by another process"
                      " (--force to skip it)")
    return fd, "watched"


def scan_markers(text, events, now):
    """Record the first time each console marker appears; return the U-Boot banner if new."""
    banner = None
    for name, pattern in MARKERS.items():
        if name not in events and (match := pattern.search(text)):
            events[name] = now
            if name == "u-boot":
                banner = match.group().decode(errors="replace").strip()
    return banner


def power_cycle(relay, target, off_seconds, timeout, console, log):
    channel = target.channel
    result = {"before": board_on_usb(target), "off_seconds": off_seconds}
    tail = bytearray()

    def pump(wait=0.1):
        if console is None:
            time.sleep(wait)
            return b""
        data = read_available(console, wait)
        if log and data:
            log.write(data)
        tail.extend(data)
        del tail[:-4096]
        return data

    progress(f"{target.name}: {result['before'] or 'not on USB'}; cutting power on {channel}")
    cut = time.monotonic()
    left = None
    try:
        switch(relay, channel, channel.coil_for(False))
        while time.monotonic() - cut < off_seconds:
            pump()
            if left is None and board_on_usb(target) is None:
                left = round(time.monotonic() - cut, 2)
                progress(f"{target.name}: left USB after {left} s")
    finally:
        restore(relay, channel, channel.coil_for(True), f"{target.name} POWER")
        progress(f"{target.name}: power restored")
    powered = time.monotonic()
    result["left_usb_after"] = left
    if result["before"] and left is None:
        result.update(exit=EXIT_NOT_CUT, outcome=f"stayed on USB for the whole cut: check that"
                      f" {channel} carries the supply through COM/{channel.wiring}")
        return result

    events, seen = {}, bytearray()
    while (now := round(time.monotonic() - powered, 2)) < timeout:
        seen += pump()
        if banner := scan_markers(seen, events, now):
            result["u_boot"] = banner
        if board_on_usb(target) == "fastboot":
            events["fastboot"] = now
            break
    result["events"] = events
    if "fastboot" in events:
        result.update(exit=EXIT_OK, outcome=f"fastboot {target.fastboot_serial} after {now} s")
    elif events:
        result.update(exit=EXIT_NO_FASTBOOT,
                      outcome=f"booted, but no fastboot within {timeout:g} s")
    else:
        result.update(exit=EXIT_NO_SIGN,
                      outcome=f"no console output or fastboot within {timeout:g} s")
    if result["exit"] and tail:
        result["console_tail"] = tail.decode(errors="replace").replace("\r", "").splitlines()[-15:]
    return result


def cmd_identify(args, config):
    nodes = candidates()
    configured = node_info(config.device)
    for node in nodes:
        access = "rw" if os.access(node.dev, os.R_OK | os.W_OK) else "no access"
        mark = f"  <- {config.device}" if configured and node.dev == configured.dev else ""
        print(f"{node}  {access}{mark}")
    if not nodes:
        print("no supported relay module (dcttech USBRelayN, 16c0:05df);"
              " compare lsusb before and after plugging it in")
        return EXIT_NO_RELAY
    if configured is None:
        print(f"{config.device} is missing; `{PROG} udev-rule` prints a rule for it")
    return EXIT_OK


def udev_rule(node, device):
    if not node.id_path:
        raise Failure(EXIT_NO_RELAY, f"udev has no ID_PATH for {node.dev}")
    vid, pid = node.vid_pid
    return (f"# Lab relay module ({node.attr('product')}) on USB port {node.id_path}.\n"
            f"# From tools/lab/relay.py udev-rule; regenerate if the module changes port.\n"
            f'SUBSYSTEM=="{node.subsystem}", ENV{{ID_PATH}}=="{node.id_path}", '
            f'ATTRS{{idVendor}}=="{vid}", ATTRS{{idProduct}}=="{pid}", '
            f'SYMLINK+="{device.removeprefix("/dev/")}", TAG+="uaccess"\n')


def cmd_udev_rule(args, config):
    nodes = [node_info(args.device)] if args.device else candidates()
    nodes = [node for node in nodes if node and node.supported]
    if len(nodes) != 1:
        raise Failure(EXIT_NO_RELAY, f"{len(nodes)} supported relay modules found; pick one"
                      " with --device")
    print(udev_rule(nodes[0], config.device), end="")
    return EXIT_OK


def cmd_status(args, config):
    node, relay = open_relay(config, args.device)
    states = relay.read()
    print(f"{node}  board ID {relay.serial}")
    for channel in config.channels.values():
        coil = states[channel.number]
        load = channel.load(coil)
        print(f"{channel}: coil {'on' if coil else 'off'}" + (f", {load}" if load else ""))
    return EXIT_OK


def cmd_switch(args, config):
    channel = config.channel(args.channel)
    coil = args.command == "on"
    guard(config, channel, coil, args.force)
    _, relay = open_relay(config, args.device)
    switch(relay, channel, coil)
    load = channel.load(coil)
    print(f"{channel}: coil {args.command}" + (f", {load}" if load else ""))
    return EXIT_OK


def cmd_pulse(args, config):
    channel = config.channel(args.channel)
    guard(config, channel, True, args.force)
    _, relay = open_relay(config, args.device)
    try:
        switch(relay, channel, True)
        progress(f"{channel}: coil on for {args.seconds:g} s")
        time.sleep(args.seconds)
    finally:
        restore(relay, channel, False, str(channel))
        progress(f"{channel}: coil off")
    return EXIT_OK


def cmd_power_cycle(args, config):
    target = config.targets.get(args.target)
    if target is None:
        raise Failure(EXIT_ERROR, f"config has no target {args.target!r}")
    off = target.off_seconds if args.off_seconds is None else args.off_seconds
    timeout = target.timeout if args.timeout is None else args.timeout
    if off < 1:
        raise Failure(EXIT_ERROR, "--off-seconds must be at least 1")
    if not args.force:
        refuse_if_busy(target)
    node, relay = open_relay(config, args.device)
    console, note = open_console(target, args.force)
    result = {"target": target.name, "relay": node.dev,
              "channel": target.channel.number, "console": note,
              "started": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        with open(args.uart_log, "ab") if args.uart_log else contextlib.nullcontext() as log:
            result |= power_cycle(relay, target, off, timeout, console, log)
    finally:
        if console is not None:
            os.close(console)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for line in result.get("console_tail", []):
            progress(f"  | {line}")
        events = ", ".join(f"{name} +{seconds} s"
                           for name, seconds in result.get("events", {}).items())
        print(f"{target.name}: {result['outcome']}" + (f" [{events}]" if events else "")
              + f" (exit {result['exit']})")
    return result["exit"]


def parser():
    top = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    top.add_argument("--config", type=Path, default=CONFIG,
                     help="channel map (default: relay.toml beside this script)")
    top.add_argument("--device", help="relay device node, overriding the config")
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("identify", help="list supported relay modules").set_defaults(run=cmd_identify)
    sub.add_parser("udev-rule", help="print a udev rule that names the module and grants"
                   " access").set_defaults(run=cmd_udev_rule)
    sub.add_parser("status", help="show every channel's coil").set_defaults(run=cmd_status)
    for name, text in (("on", "energise a coil (NO closes, NC opens)"),
                       ("off", "release a coil (NC closes, NO opens)")):
        command = sub.add_parser(name, help=text)
        command.add_argument("channel", help="channel number or name")
        command.add_argument("--force", action="store_true",
                             help="skip the busy check when this cuts a target's power")
        command.set_defaults(run=cmd_switch)
    pulse = sub.add_parser("pulse", help="energise a coil, wait, release it")
    pulse.add_argument("channel", help="channel number or name")
    pulse.add_argument("--seconds", type=float, default=1.0)
    pulse.add_argument("--force", action="store_true",
                       help="skip the busy check when this cuts a target's power")
    pulse.set_defaults(run=cmd_pulse)
    cycle = sub.add_parser("db410c-power-cycle", help="cut the DB410c's power, restore it and"
                           " wait for its fastboot")
    cycle.add_argument("--force", action="store_true",
                       help="act even though the board looks in use")
    cycle.add_argument("--off-seconds", type=float, help="how long power stays off")
    cycle.add_argument("--timeout", type=float, help="seconds to wait after power returns")
    cycle.add_argument("--uart-log", type=Path, help="append raw console bytes to this file")
    cycle.add_argument("--json", action="store_true", help="print the result as JSON")
    cycle.set_defaults(run=cmd_power_cycle, target="db410c")
    return top


def interrupt(signum, frame):
    raise KeyboardInterrupt(signal.Signals(signum).name)


def main(argv=None):
    args = parser().parse_args(argv)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupt)
    try:
        return args.run(args, load_config(args.config))
    except Failure as failure:
        print(f"{PROG}: {failure}", file=sys.stderr)
        return failure.code
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return EXIT_ERROR
    except (OSError, termios.error) as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
