#!/usr/bin/env python3
"""Exercise the libcamera session helper with stub cam/power/magick tools.

No camera, DRM device, gate or hardware is touched. The helper's root/preflight
entry is bypassed in favour of its run_session path run in a real subprocess,
so cancellation and process-group cleanup are tested for real.
"""

import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock


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
        self.write("cam-system-heap", textwrap.dedent('''
            import os, re, sys, time
            args = sys.argv[1:]
            capture = None
            pattern = None
            if os.environ.get("STUB_CAM_ARGS"):
                open(os.environ["STUB_CAM_ARGS"], "w").write(" ".join(args))
            if os.environ.get("STUB_CAM_PID"):
                open(os.environ["STUB_CAM_PID"], "w").write(str(os.getpid()))
            for arg in args:
                if arg.startswith("--capture="):
                    capture = int(arg.split("=", 1)[1])
                elif arg.startswith("--file="):
                    pattern = arg.split("=", 1)[1].replace("#", "{}")
            frames = int(os.environ.get("STUB_CAM_FRAMES", capture))
            delay = float(os.environ.get("STUB_CAM_DELAY", "0.15"))
            peak_file = os.environ.get("STUB_CAM_PEAK")
            peak = 0
            for index in range(frames):
                directory = os.path.dirname(pattern)
                present = len([f for f in os.listdir(directory)
                               if re.fullmatch(r"frame-\\d+\\.ppm", f)])
                peak = max(peak, present + 1)
                if peak_file:
                    open(peak_file, "w").write(str(peak))
                open(pattern.format(index), "w").write("P6\\n1280 960\\n255\\n")
                print("Metadata: ExposureTime", 100 + index,
                      "AnalogueGain", 1.0 + index / 10, flush=True)
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


class PrunerTests(Base):
    def test_pruner_keeps_only_the_newest_frames(self):
        frames = self.root / "frames"
        frames.mkdir()
        log = self.root / "cam.log"
        peak = self.root / "peak"
        env = self.base_env(STUB_CAM_PEAK=str(peak), STUB_CAM_DELAY="0.15")
        command = [str(self.bin / "cam-system-heap"), "--capture=6",
                   f"--file={frames}/frame-#.ppm"]
        with mock.patch.dict(os.environ, env):
            result = MODULE["run_cam"](command, log, 60, frames, 2)
        self.assertEqual(result["returncode"], 0, result)
        self.assertEqual(result["remaining"], [])
        self.assertEqual(result["max_index"], 5)
        self.assertLessEqual(int(peak.read_text()), 4)
        remaining = sorted(path.name for path in frames.glob("frame-*.ppm"))
        self.assertEqual(remaining, ["frame-4.ppm", "frame-5.ppm"])


class SessionTests(Base):
    def test_happy_path_bounded_warmup_and_jpeg(self):
        cam_args = self.root / "cam-args"
        result = self.run_session(self.out, ["--warmup", "4", "--keep", "2"],
                                  env=self.base_env(STUB_CAM_ARGS=str(cam_args)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["capture_total"], 5)
        self.assertTrue(Path(report["jpeg"]).is_file())
        self.assertEqual(report["geometry"], "JPEG 1280 960")
        tokens = cam_args.read_text().split()
        self.assertIn("--capture=5", tokens)
        self.assertIn("--metadata", tokens)
        self.assertIn(f"--file={self.out}/frame-#.ppm", tokens)
        self.assertIn("--stream=role=still,width=1280,height=960,pixelformat=RGB888",
                      tokens)
        self.assertNotIn("--display", tokens)
        self.assertIn("Metadata", (self.out / "cam.log").read_text())
        self.assertEqual(sorted(p.name for p in self.out.glob("frame-*.ppm")),
                         ["frame-3.ppm", "frame-4.ppm"])

    def test_too_few_frames_fails(self):
        result = self.run_session(self.out, ["--warmup", "4"],
                                  env=self.base_env(STUB_CAM_FRAMES="2"))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIn("frames", report["error"])

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
        result = self.run_session(self.out, ["--warmup", "1"],
                                  env=self.base_env(STUB_POWER_FAIL="after",
                                                    STUB_POWER_COUNT=str(self.root / "power-count")))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIsNotNone(report["jpeg"])

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
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "cancelled")
        deadline = time.monotonic() + 3
        state = Path(f"/proc/{cam_pid}/stat")
        while state.exists() and time.monotonic() < deadline:
            if state.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"}:
                break
            time.sleep(0.05)
        if state.exists():
            self.assertIn(state.read_text().rsplit(")", 1)[1].split()[0], {"Z", "X"},
                          "cam survived cancellation")


class ContractTests(Base):
    def parser(self, *argv):
        return MODULE["build_parser"](HERE.parent).parse_args(
            ["--output", str(self.root / "plan"), *argv])

    def test_display_passthrough_forms(self):
        build = MODULE["build_cam_command"]
        self.assertNotIn("--display",
                         build(self.parser(), 5, "/tmp/frame-#.ppm"))
        self.assertIn("--display",
                      build(self.parser("--display"), 5, "/tmp/frame-#.ppm"))
        self.assertIn("--display=DSI-1",
                      build(self.parser("--display=DSI-1"), 5, "/tmp/frame-#.ppm"))

    def test_only_documented_cam_options_are_used(self):
        tokens = MODULE["build_cam_command"](
            self.parser("--display=DSI-1"), 5, "/tmp/frame-#.ppm")
        options = {token.split("=", 1)[0] for token in tokens if token.startswith("--")}
        self.assertLessEqual(options, set(MODULE["CAM_OPTIONS"]))

    def test_preflight_reports_missing_magick(self):
        args = self.parser("--magick", "definitely-not-a-real-binary")
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


if __name__ == "__main__":
    unittest.main()
