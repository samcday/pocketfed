#!/usr/bin/env python3
"""Exercise the libcamera helper with stub cam/power/magick tools.

No camera, DRM, gate or hardware is touched. run_session is run in a real
subprocess (bypassing only the root/preflight entry) so cancellation and
process-group cleanup are exercised for real.
"""

import json
import io
import os
from pathlib import Path
import re
import runpy
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stderr


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "libcamera-session.py"
MODULE = runpy.run_path(str(SCRIPT))

BOOTSTRAP = (
    "import runpy, sys\n"
    "from pathlib import Path\n"
    "m = runpy.run_path(sys.argv[1])\n"
    "parser = m['build_parser'](Path(sys.argv[2]))\n"
    "args = parser.parse_args(sys.argv[3:])\n"
    "report = m['Reporter'](sys.stdout, Path(args.output) / 'status')\n"
    "sys.exit(m['run_session'](args, report))\n"
)


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sargo-libcam-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.out = self.root / "out"
        self.write_cam_stub()
        self.write_power_stub()
        self.write_magick_stub()

    def write(self, name, body, python=True):
        path = self.bin / name
        path.write_text(("#!/usr/bin/env python3\n" + body) if python else body)
        path.chmod(0o755)
        return path

    def write_cam_stub(self):
        # Emulates the source contract: a fixed --file is truncated each frame,
        # and each completed request prints the camera_session.cpp info line.
        self.write("cam-system-heap", textwrap.dedent('''
            import os, re, sys, time
            args = sys.argv[1:]
            capture = None
            output = None
            if os.environ.get("STUB_CAM_ARGS"):
                open(os.environ["STUB_CAM_ARGS"], "w").write(" ".join(args))
            if os.environ.get("STUB_CAM_PID"):
                open(os.environ["STUB_CAM_PID"], "w").write(str(os.getpid()))
            for arg in args:
                if arg.startswith("--capture="):
                    capture = int(arg.split("=", 1)[1])
                elif arg.startswith("--file="):
                    output = arg.split("=", 1)[1]
            frames = int(os.environ.get("STUB_CAM_FRAMES", capture))
            delay = float(os.environ.get("STUB_CAM_DELAY", "0.05"))
            for index in range(frames):
                with open(output, "w") as frame:      # PPMWriter truncates
                    frame.write("P6\\n1280 960\\n255\\n")
                print(f"{index}.000000 (30.00 fps) cam0-stream0 seq: {index:06d} "
                      f"bytesused: 3686400", flush=True)
                print("\\tExposureTime = %d" % (1000 + index), flush=True)
                print("\\tAnalogueGain = 1.0", flush=True)
                time.sleep(delay)
        '''))

    def write_power_stub(self):
        self.write("power-state.py", textwrap.dedent('''
            import os, sys
            counter = os.environ.get("STUB_POWER_COUNT")
            calls = 0
            if counter and os.path.exists(counter):
                calls = int(open(counter).read())
            calls += 1
            if counter:
                open(counter, "w").write(str(calls))
            fail = os.environ.get("STUB_POWER_FAIL", "")
            if (fail == "before" and calls == 1) or (fail == "after" and calls >= 2):
                sys.exit(1)
            print('{"release_status": "released"}')
            sys.exit(0)
        '''))

    def write_magick_stub(self):
        self.write("magick", textwrap.dedent('''
            import os, shutil, sys
            args = sys.argv[1:]
            if args and args[0] == "identify":
                kind = "JPEG" if args[-1].lower().endswith(".jpg") else "PPM"
                size = "1 1" if os.environ.get("STUB_BAD_GEOMETRY") else "1280 960"
                print(f"{kind} {size}")
                sys.exit(0)
            if "null:" in args:
                sys.exit(1 if os.environ.get("STUB_MAGICK_DECODE_FAIL") else 0)
            if len(args) >= 2:
                shutil.copyfile(args[0], args[1])
                sys.exit(0)
            sys.exit(1)
        '''))

    def base_env(self, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ.get('PATH', '')}")
        env.update(extra)
        return env

    def session_args(self, output, extra=()):
        return ["--output", str(output),
                "--cam-entry", str(self.bin / "cam-system-heap"),
                "--power-state", str(self.bin / "power-state.py"),
                "--magick", str(self.bin / "magick"), *extra]

    def run_session(self, output, extra=(), env=None, wait=True):
        command = [sys.executable, "-c", BOOTSTRAP, str(SCRIPT),
                   str(SCRIPT.parent.parent), *self.session_args(output, extra)]
        if wait:
            return subprocess.run(command, env=env or self.base_env(),
                                  capture_output=True, text=True, timeout=120)
        return subprocess.Popen(command, env=env or self.base_env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)

    def read_result(self, output):
        return json.loads((output / "result.json").read_text())


class SourceContractTests(Base):
    def test_fixed_ppm_file_has_no_hash_and_never_expands(self):
        command = MODULE["build_cam_command"](
            MODULE["build_parser"](HERE.parent).parse_args(
                ["--output", str(self.root / "plan")]),
            91, self.root / "frame.ppm")
        self.assertIn(f"--capture=91", command)
        self.assertIn("--metadata", command)
        self.assertNotIn("--display", command)
        file_token = next(token for token in command if token.startswith("--file="))
        self.assertTrue(file_token.endswith(".ppm"))
        self.assertNotIn("#", file_token)

    def test_hash_expansion_would_break_frame_digits_matching(self):
        # file_sink.cpp expands the first '#' to "<streamName>-<sequence>", and
        # camera_session.cpp builds streamName as "cam<idx>-stream<idx>".
        expanded = "frame-" + "cam0-stream0" + "-" + f"{123:06d}" + ".ppm"
        self.assertEqual(expanded, "frame-cam0-stream0-000123.ppm")
        self.assertIsNone(re.fullmatch(r"frame-\d+\.ppm", expanded))

    def test_sequence_parser_matches_camera_session_output(self):
        log = textwrap.dedent("""
            12.345678 (30.00 fps) cam0-stream0 seq: 000000 bytesused: 3686400
            \tExposureTime = 1000
            \tAnalogueGain = 1.0
            12.379012 (29.98 fps) cam0-stream0 seq: 000001 bytesused: 3686400
            \tExposureTime = 1000
        """)
        count, low, high = MODULE["frame_sequences"](log)
        self.assertEqual((count, low, high), (2, 0, 1))

    def test_frame_count_is_not_derived_from_sequence_max(self):
        # Sequences can start above zero and skip values; the count is the
        # number of completed-request lines, not max+1. Metadata control lines
        # (tab-indented, no "bytesused:") must not be counted.
        log = "\n".join([
            "1.000000 (30.00 fps) cam0-stream0 seq: 000005 bytesused: 1",
            "\tExposureTime = 1000",
            "2.000000 (30.00 fps) cam0-stream0 seq: 000007 bytesused: 1",
            "3.000000 (30.00 fps) cam0-stream0 seq: 000008 bytesused: 1",
        ])
        count, low, high = MODULE["frame_sequences"](log)
        self.assertEqual(count, 3)
        self.assertNotEqual(count, high + 1)
        self.assertEqual((low, high), (5, 8))

    def test_display_option_is_not_offered(self):
        self.assertEqual(set(MODULE["CAM_OPTIONS"]),
                         {"-c", "--stream", "--capture", "--file", "--metadata"})
        parser = MODULE["build_parser"](HERE.parent)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--output", str(self.root / "x"), "--display"])

    def test_preflight_reports_missing_magick(self):
        args = MODULE["build_parser"](HERE.parent).parse_args(
            ["--output", str(self.root / "x"),
             "--magick", "definitely-not-a-real-binary"])
        with self.assertRaises(MODULE["SessionError"]):
            MODULE["preflight"](args)

    def test_main_requires_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        with self.assertRaises(SystemExit) as caught:
            MODULE["main"](["--output", str(self.root / "root-check"),
                            "--cam-entry", str(self.bin / "cam-system-heap"),
                            "--power-state", str(self.bin / "power-state.py")])
        self.assertIn("root", str(caught.exception))


class SessionTests(Base):
    def test_happy_path_fixed_frame_and_jpeg(self):
        cam_args = self.root / "cam-args"
        result = self.run_session(self.out, ["--warmup", "2"],
                                  env=self.base_env(STUB_CAM_ARGS=str(cam_args)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["capture_total"], 3)
        self.assertEqual(report["frames_captured"], 3)
        self.assertEqual(report["sequence_min"], 0)
        self.assertEqual(report["sequence_max"], 2)
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertIsNone(report["release_error"])
        self.assertEqual(report["ppm"], str(self.out / "frame.ppm"))
        self.assertTrue(Path(report["jpeg"]).is_file())
        self.assertEqual(report["geometry"], "JPEG 1280 960")
        tokens = cam_args.read_text().split()
        self.assertIn("--capture=3", tokens)
        self.assertIn("--metadata", tokens)
        self.assertFalse(any("#" in token for token in tokens))
        self.assertIn("ExposureTime", (self.out / "cam.log").read_text())
        self.assertEqual(list(self.out.glob("frame-*.ppm")), [])

    def test_fewer_completed_frames_than_expected_fails(self):
        result = self.run_session(self.out, ["--warmup", "4"],
                                  env=self.base_env(STUB_CAM_FRAMES="2"))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["frames_captured"], 2)
        self.assertIn("completed frames", report["error"])

    def test_decode_failure_fails(self):
        result = self.run_session(self.out, ["--warmup", "1"],
                                  env=self.base_env(STUB_MAGICK_DECODE_FAIL="1"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("decode", self.read_result(self.out)["error"])

    def test_bad_geometry_fails(self):
        result = self.run_session(self.out, ["--warmup", "1"],
                                  env=self.base_env(STUB_BAD_GEOMETRY="1"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("geometry", self.read_result(self.out)["error"])

    def test_pre_release_failure_aborts_before_capture(self):
        cam_args = self.root / "cam-args-before"
        result = self.run_session(self.out, ["--warmup", "1"],
                                  env=self.base_env(STUB_POWER_FAIL="before",
                                                    STUB_CAM_ARGS=str(cam_args)))
        self.assertEqual(result.returncode, 1)
        self.assertFalse(cam_args.exists(), "cam must not start without release")

    def test_post_release_failure_fails_after_capture(self):
        counts = self.root / "power-count"
        result = self.run_session(
            self.out, ["--warmup", "1"],
            env=self.base_env(STUB_POWER_FAIL="after", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIs(report["camera_released"], False)
        self.assertIsNotNone(report["release_error"])
        self.assertEqual(counts.read_text(), "2")

    def test_post_release_runs_after_cam_timeout_and_keeps_cause(self):
        counts = self.root / "power-count-timeout"
        result = self.run_session(
            self.out, ["--warmup", "1", "--timeout", "1"],
            env=self.base_env(STUB_CAM_DELAY="5", STUB_POWER_FAIL="after",
                              STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["cam"]["timed_out"], True)
        self.assertEqual(report["status"], "failed")
        self.assertIs(report["camera_released"], False)
        self.assertIn("cam run failed", report["error"])       # cause retained
        self.assertIsNotNone(report["release_error"])          # failure recorded
        self.assertEqual(counts.read_text(), "2")

    def test_post_release_runs_after_decode_failure_and_keeps_cause(self):
        counts = self.root / "power-count-decode"
        result = self.run_session(
            self.out, ["--warmup", "1"],
            env=self.base_env(STUB_MAGICK_DECODE_FAIL="1", STUB_POWER_FAIL="after",
                              STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIn("decode", report["error"])               # cause retained
        self.assertIs(report["camera_released"], False)
        self.assertIsNotNone(report["release_error"])
        self.assertEqual(counts.read_text(), "2")

    def test_repeated_sigterm_does_not_skip_release_or_cleanup(self):
        counts = self.root / "power-count-cancel"
        cam_pid_file = self.root / "cam-pid-cancel"
        process = self.run_session(
            self.out, ["--warmup", "4", "--timeout", "60"],
            env=self.base_env(STUB_CAM_DELAY="5", STUB_CAM_PID=str(cam_pid_file),
                              STUB_POWER_COUNT=str(counts)),
            wait=False)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not cam_pid_file.exists():
                if process.poll() is not None:
                    self.fail("helper exited before cam started: "
                              + process.stdout.read())
                time.sleep(0.05)
            self.assertTrue(cam_pid_file.exists(), "cam never started")
            cam_pid = int(cam_pid_file.read_text())
            process.send_signal(signal.SIGTERM)
            time.sleep(0.1)
            process.send_signal(signal.SIGTERM)      # repeated cancellation
            process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        self.assertEqual(process.returncode, 143)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "cancelled")
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)   # release still ran
        self.assertEqual(counts.read_text(), "2")
        state = Path(f"/proc/{cam_pid}/stat")
        if state.exists():
            self.assertIn(state.read_text().rsplit(")", 1)[1].split()[0], {"Z", "X"},
                          "cam survived repeated cancellation")

    def test_sigterm_cancels_and_kills_cam(self):
        cam_pid_file = self.root / "cam-pid"
        process = self.run_session(
            self.out, ["--warmup", "4", "--timeout", "60"],
            env=self.base_env(STUB_CAM_PID=str(cam_pid_file), STUB_CAM_DELAY="5"),
            wait=False)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not cam_pid_file.exists():
                if process.poll() is not None:
                    self.fail("helper exited before cam started: "
                              + process.stdout.read())
                time.sleep(0.05)
            self.assertTrue(cam_pid_file.exists(), "cam never started")
            cam_pid = int(cam_pid_file.read_text())
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=20)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        self.assertEqual(process.returncode, 143)
        self.assertEqual(self.read_result(self.out)["status"], "cancelled")
        deadline = time.monotonic() + 3
        state = Path(f"/proc/{cam_pid}/stat")
        while state.exists() and time.monotonic() < deadline:
            if state.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"}:
                break
            time.sleep(0.05)
        if state.exists():
            self.assertIn(state.read_text().rsplit(")", 1)[1].split()[0], {"Z", "X"},
                          "cam survived cancellation")


if __name__ == "__main__":
    unittest.main()
