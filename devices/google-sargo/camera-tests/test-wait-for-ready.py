#!/usr/bin/env python3
"""Exercise readiness parsing, state failures and child cleanup without hardware."""

import io
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock


MODULE = runpy.run_path(str(Path(__file__).with_name("wait-for-ready.py")))
InputEvent = MODULE["InputEvent"]
SYN_DROPPED = MODULE["SYN_DROPPED"]
Gate = MODULE["Gate"]
Reporter = MODULE["Reporter"]
parse_events = MODULE["parse_events"]
INPUT_EVENT = MODULE["INPUT_EVENT"]
EventReader = MODULE["EventReader"]
DeviceDisconnected = MODULE["DeviceDisconnected"]
EV_KEY = MODULE["EV_KEY"]
EV_SYN = MODULE["EV_SYN"]
SYN_DROPPED_CODE = MODULE["SYN_DROPPED_CODE"]
KEY_VOLUMEUP = MODULE["KEY_VOLUMEUP"]
KEY_VOLUMEDOWN = MODULE["KEY_VOLUMEDOWN"]
wait_for_readiness = MODULE["wait_for_readiness"]


class Clock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class RisingClock:
    """Advances on every read so bounded loops terminate without real waiting."""

    def __init__(self, step=100.0):
        self.value = 0.0
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


def press(code):
    return InputEvent(EV_KEY, code, 1)


def release(code):
    return InputEvent(EV_KEY, code, 0)


def repeat(code):
    return InputEvent(EV_KEY, code, 2)


class GateTests(unittest.TestCase):
    def make(self, settle=3.0):
        clock = Clock()
        seen = []
        gate = Gate(settle=settle, on_state=lambda s, d: seen.append(s), clock=clock)
        gate.resync(set())
        return gate, clock, seen

    def test_fresh_press_release_settles_then_authorizes(self):
        gate, clock, _ = self.make()
        gate.feed(press(KEY_VOLUMEUP))
        self.assertEqual(gate.state, "waiting")
        gate.feed(release(KEY_VOLUMEUP))
        self.assertEqual(gate.state, "settling")
        clock.advance(2.9)
        gate.tick()
        self.assertEqual(gate.state, "settling")
        clock.advance(0.2)
        gate.tick()
        self.assertEqual(gate.state, "authorized")

    def test_repeats_never_authorize(self):
        gate, _, _ = self.make()
        for _ in range(5):
            gate.feed(repeat(KEY_VOLUMEUP))
        gate.tick()
        self.assertEqual(gate.state, "waiting")

    def test_release_without_fresh_press_is_ignored(self):
        gate, _, _ = self.make()
        gate.feed(release(KEY_VOLUMEUP))
        gate.tick()
        self.assertEqual(gate.state, "waiting")

    def test_initially_held_volume_up_requires_release_then_fresh_press(self):
        gate, _, _ = self.make()
        gate.resync({KEY_VOLUMEUP})
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(release(KEY_VOLUMEUP))
        self.assertEqual(gate.state, "waiting")
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(release(KEY_VOLUMEUP))
        self.assertEqual(gate.state, "settling")

    def test_initially_held_volume_down_release_does_not_cancel(self):
        gate, _, _ = self.make()
        gate.resync({KEY_VOLUMEDOWN})
        gate.feed(release(KEY_VOLUMEDOWN))
        self.assertEqual(gate.state, "waiting")
        gate.feed(press(KEY_VOLUMEDOWN))
        self.assertEqual(gate.state, "cancelled")

    def test_volume_down_cancels_waiting(self):
        gate, _, _ = self.make()
        gate.feed(press(KEY_VOLUMEDOWN))
        self.assertEqual(gate.state, "cancelled")

    def test_volume_down_cancels_settling(self):
        gate, _, _ = self.make()
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(release(KEY_VOLUMEUP))
        self.assertEqual(gate.state, "settling")
        gate.feed(press(KEY_VOLUMEDOWN))
        self.assertEqual(gate.state, "cancelled")
        gate.tick()
        self.assertNotEqual(gate.state, "authorized")

    def test_syn_dropped_discards_partial_press(self):
        gate, _, _ = self.make()
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(SYN_DROPPED)
        gate.feed(release(KEY_VOLUMEUP))
        gate.tick()
        self.assertEqual(gate.state, "waiting")

    def test_syn_dropped_during_settle_cancels(self):
        gate, _, _ = self.make()
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(release(KEY_VOLUMEUP))
        gate.feed(SYN_DROPPED)
        self.assertEqual(gate.state, "cancelled")

    def test_expire_only_stops_waiting(self):
        gate, _, _ = self.make()
        gate.expire()
        self.assertEqual(gate.state, "timeout")

    def test_disconnect_during_settle_cancels(self):
        gate, _, _ = self.make()
        gate.feed(press(KEY_VOLUMEUP))
        gate.feed(release(KEY_VOLUMEUP))
        gate.disconnected()
        self.assertEqual(gate.state, "cancelled")


class ParserTests(unittest.TestCase):
    def test_parse_multiple_with_leftover(self):
        raw = b"".join(INPUT_EVENT.pack(0, 0, EV_KEY, KEY_VOLUMEUP, 1) for _ in range(2))
        events, leftover = parse_events(raw + b"\x00\x01")
        self.assertEqual([(e.type, e.code, e.value) for e in events],
                         [(EV_KEY, KEY_VOLUMEUP, 1)] * 2)
        self.assertEqual(leftover, b"\x00\x01")

    def test_syn_dropped_is_a_distinct_marker(self):
        events, _ = parse_events(INPUT_EVENT.pack(0, 0, EV_SYN, SYN_DROPPED_CODE, 0))
        self.assertEqual(events, [SYN_DROPPED])

    def test_reader_buffers_split_struct_then_reports_disconnect(self):
        read_fd, write_fd = os.pipe()
        try:
            reader = EventReader(read_fd, "pipe")
            raw = INPUT_EVENT.pack(0, 0, EV_KEY, KEY_VOLUMEUP, 1)
            os.write(write_fd, raw[:5])
            self.assertEqual(reader.read(), [])
            os.write(write_fd, raw[5:])
            events = reader.read()
            self.assertEqual([(e.type, e.code, e.value) for e in events],
                             [(EV_KEY, KEY_VOLUMEUP, 1)])
            os.close(write_fd)
            with self.assertRaises(DeviceDisconnected):
                reader.read()
        finally:
            os.close(read_fd)


class CapabilityTests(unittest.TestCase):
    def test_decode_bitmap_finds_only_set_keys(self):
        data = bytearray(96)
        data[KEY_VOLUMEUP // 8] |= 1 << (KEY_VOLUMEUP % 8)
        bits = MODULE["decode_key_bitmap"](bytes(data))
        self.assertIn(KEY_VOLUMEUP, bits)
        self.assertNotIn(KEY_VOLUMEDOWN, bits)

    def test_non_input_fd_is_rejected_without_crashing(self):
        self.assertEqual(MODULE["open_capable"]([Path("/dev/null")]), [])


class CommandTests(unittest.TestCase):
    def test_normalize_command_strips_the_remainder_dash(self):
        normalize = MODULE["normalize_command"]
        self.assertEqual(normalize(["--", "cam", "--capture=1"]),
                         ["cam", "--capture=1"])
        self.assertEqual(normalize(["cam"]), ["cam"])
        self.assertEqual(normalize([]), None)


class ReporterTests(unittest.TestCase):
    def test_status_file_is_private_and_single_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "status"
            reporter = Reporter(io.StringIO(), status_file=path, quiet=True)
            reporter.state("waiting", "x" * 500 + "\nsecond")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            text = path.read_text()
            self.assertIn("state=waiting", text)
            self.assertNotIn("second", text)


class CleanupTests(unittest.TestCase):
    def test_run_capture_kills_child_that_ignores_term_on_timeout(self):
        script = textwrap.dedent('''
            import subprocess, sys, signal, time
            child = subprocess.Popen([sys.executable, "-c",
                "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"])
            print(child.pid, flush=True)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            time.sleep(60)
        ''')
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "capture.log"
            result = MODULE["run_capture"]([sys.executable, "-c", script], 1, str(log))
            child_pid = int(log.read_text().splitlines()[0])
            state = Path(f"/proc/{child_pid}/stat")
            self.assertTrue(not state.exists()
                            or state.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"})
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["remaining_processes"], [])

    def test_run_capture_reports_success(self):
        result = MODULE["run_capture"]([sys.executable, "-c", "raise SystemExit(0)"], 5, None)
        self.assertEqual(result["returncode"], 0)
        self.assertFalse(result["timed_out"])


class RunnerTests(unittest.TestCase):
    class Reader:
        def __init__(self, fd, batches):
            self.fd = fd
            self.path = f"reader-{fd}"
            self.batches = list(batches)

        def read(self):
            if not self.batches:
                raise DeviceDisconnected("drained")
            return self.batches.pop(0)

    def make_gate(self, reporter):
        clock = Clock()
        return Gate(settle=0.0, on_state=reporter.state, clock=clock), clock

    @staticmethod
    def ready(fds, _w, _x, _timeout):
        return (list(fds), [], [])

    def test_authorized_command_runs_exactly_once(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        reader = self.Reader(11, [[press(KEY_VOLUMEUP)], [release(KEY_VOLUMEUP)]])
        calls = []

        def capture(command, timeout, log):
            calls.append(command)
            return {"returncode": 0, "timed_out": False, "remaining_processes": []}

        code = wait_for_readiness(
            [reader], gate, timeout=10, reporter=reporter, command=["capture"],
            capture_timeout=5, select_fn=self.ready, clock=clock,
            sleep_fn=lambda _seconds: None, capture=capture)
        self.assertEqual(gate.state, "authorized")
        self.assertEqual(calls, [["capture"]])
        self.assertEqual(code, 0)

    def test_real_pipe_events_authorize_through_real_select(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        read_fd, write_fd = os.pipe()
        try:
            reader = EventReader(read_fd, "pipe")
            with tempfile.TemporaryDirectory() as temporary:
                marker = Path(temporary) / "ran"

                def writer():
                    time.sleep(0.05)
                    os.write(write_fd, INPUT_EVENT.pack(0, 0, EV_KEY, KEY_VOLUMEUP, 1))
                    os.write(write_fd, INPUT_EVENT.pack(0, 0, EV_KEY, KEY_VOLUMEUP, 0))

                thread = threading.Thread(target=writer)
                thread.start()
                code = wait_for_readiness(
                    [reader], gate, timeout=5, reporter=reporter,
                    command=[sys.executable, "-c",
                             f"open({str(marker)!r}, 'w').write('once')"],
                    capture_timeout=5, clock=clock, sleep_fn=time.sleep)
                thread.join()
                self.assertEqual(code, 0)
                self.assertEqual(gate.state, "authorized")
                self.assertEqual(marker.read_text(), "once")
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_authorized_command_reaches_a_real_child_once(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        reader = self.Reader(11, [[press(KEY_VOLUMEUP)], [release(KEY_VOLUMEUP)]])
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "ran"
            command = MODULE["normalize_command"]([
                "--", sys.executable, "-c",
                f"open({str(marker)!r}, 'w').write('once')"])
            code = wait_for_readiness(
                [reader], gate, timeout=10, reporter=reporter, command=command,
                capture_timeout=5, select_fn=self.ready, clock=clock,
                sleep_fn=lambda _seconds: None)
            self.assertEqual(code, 0)
            self.assertEqual(marker.read_text(), "once")

    def test_timeout_never_runs_command(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        calls = []

        def capture(*args):
            calls.append(args)

        code = wait_for_readiness(
            [self.Reader(11, [])], gate, timeout=10, reporter=reporter,
            command=["capture"], capture_timeout=5,
            select_fn=lambda fds, _w, _x, _t: ([], [], []), clock=RisingClock(),
            sleep_fn=lambda _seconds: None, capture=capture)
        self.assertEqual(code, 3)
        self.assertEqual(gate.state, "timeout")
        self.assertEqual(calls, [])

    def test_disconnect_never_authorizes(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        code = wait_for_readiness(
            [self.Reader(11, [])], gate, timeout=0.3, reporter=reporter,
            command=["capture"], capture_timeout=5, select_fn=self.ready,
            sleep_fn=lambda _seconds: None,
            capture=lambda *a: (_ for _ in ()).throw(AssertionError("captured")))
        self.assertEqual(code, 3)
        self.assertEqual(gate.state, "timeout")

    def test_grab_is_attempted_before_reading_and_released(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        reader = self.Reader(99, [[press(KEY_VOLUMEUP)], [release(KEY_VOLUMEUP)]])
        calls = []

        def fake_ioctl(fd, request, arg=0):
            calls.append((fd, request, arg))
            return 0

        with mock.patch.object(MODULE["fcntl"], "ioctl", fake_ioctl):
            code = wait_for_readiness(
                [reader], gate, timeout=10, reporter=reporter, grab=True,
                select_fn=self.ready, clock=clock, sleep_fn=lambda _seconds: None,
                capture=lambda *a: {"returncode": 0, "timed_out": False,
                                    "remaining_processes": []})
        self.assertEqual(code, 0)
        grab_request = MODULE["eviocgrab"]()
        self.assertIn((99, grab_request, 1), calls)
        self.assertIn((99, grab_request, 0), calls)
        self.assertLess(calls.index((99, grab_request, 1)),
                        calls.index((99, grab_request, 0)))

    def test_grab_failure_is_not_fatal_and_still_authorizes(self):
        reporter = Reporter(io.StringIO(), quiet=True)
        gate, clock = self.make_gate(reporter)
        gate.resync(set())
        reader = self.Reader(99, [[press(KEY_VOLUMEUP)], [release(KEY_VOLUMEUP)]])

        def failing_ioctl(_fd, _request, _arg=0):
            raise OSError(16, "Device or resource busy")

        with mock.patch.object(MODULE["fcntl"], "ioctl", failing_ioctl):
            code = wait_for_readiness(
                [reader], gate, timeout=10, reporter=reporter, grab=True,
                select_fn=self.ready, clock=clock, sleep_fn=lambda _seconds: None,
                capture=lambda *a: {"returncode": 0, "timed_out": False,
                                    "remaining_processes": []})
        self.assertEqual(code, 0)
        self.assertEqual(gate.state, "authorized")


if __name__ == "__main__":
    unittest.main()
