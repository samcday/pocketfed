#!/usr/bin/env python3
"""Exercise the qcam session's subprocess and cleanup behavior.

Everything runs with stub phoc/qcam/power/magick/gsettings tools in a temporary
directory; no DRM, compositor, camera, gate, network or hardware is touched.
run_session is run in a real subprocess (bypassing only the root/preflight
entry) so cancellation and process-group cleanup are exercised for real.
"""

import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "qcam-session.py"

BOOTSTRAP = (
    "import runpy, sys\n"
    "from pathlib import Path\n"
    "m = runpy.run_path(sys.argv[1])\n"
    "parser = m['build_parser']()\n"
    "args = parser.parse_args(sys.argv[2:])\n"
    "report = m['Reporter'](sys.stdout, Path(args.output) / 'status')\n"
    "sys.exit(m['run_session'](args, report))\n"
)


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sargo-qcam-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.out = self.root / "out"
        self.write_phoc()
        self.write_qcam_wrapper()
        self.write_power_stub()
        self.write_magick_stub()
        self.write("true", "#!/bin/sh\nexit 0\n", python=False)

    def write(self, name, body, python=True):
        path = self.bin / name
        path.write_text(("#!/usr/bin/env python3\n" + body) if python else body)
        path.chmod(0o755)
        return path

    def write_phoc(self):
        self.write("phoc", textwrap.dedent('''
            import os, sys, time
            args = sys.argv[1:]
            socket = "pocketfed-qcam"
            if "--socket" in args:
                socket = args[args.index("--socket") + 1]
            runtime = os.environ["XDG_RUNTIME_DIR"]
            open(os.path.join(runtime, "phoc.pid"), "w").write(str(os.getpid()))
            open(os.path.join(runtime, socket), "w").close()
            if os.environ.get("STUB_PHOC_FAIL"):
                sys.exit(3)
            time.sleep(3600)
        '''))

    def write_qcam_wrapper(self):
        # Emulates cam-system-heap's allowlist switch and the patched qcam save.
        self.write("cam-system-heap", textwrap.dedent('''
            import os, sys, time
            args = sys.argv[1:]
            if args[:2] == ["--tool", "qcam"]:
                args = args[2:]
            if os.environ.get("STUB_QCAM_ARGS"):
                open(os.environ["STUB_QCAM_ARGS"], "w").write(" ".join(args))
            if os.environ.get("STUB_QCAM_PID"):
                open(os.environ["STUB_QCAM_PID"], "w").write(str(os.getpid()))
            output = None
            for index, arg in enumerate(args):
                if arg == "--output":
                    output = args[index + 1]
            if not os.environ.get("STUB_NO_JPEG") and output:
                with open(output, "wb") as jpeg:
                    jpeg.write(b"\\xff\\xd8\\xff" + b"0" * 64)
            time.sleep(float(os.environ.get("STUB_QCAM_DELAY", "0")))
            sys.exit(0)
        '''))

    def write_power_stub(self):
        self.write("power-state.py", textwrap.dedent('''
            import os, sys
            counter = os.environ.get("STUB_POWER_COUNT")
            calls = int(open(counter).read()) if counter and os.path.exists(counter) else 0
            calls += 1
            if counter:
                open(counter, "w").write(str(calls))
            if os.environ.get("STUB_POWER_FAIL") == "after" and calls >= 2:
                sys.exit(1)
            print('{"release_status": "released"}')
            sys.exit(0)
        '''))

    def write_magick_stub(self):
        self.write("magick", textwrap.dedent('''
            import sys
            args = sys.argv[1:]
            if args and args[0] == "identify":
                print("JPEG 1280 960")
                sys.exit(0)
            sys.exit(0)
        '''))

    def base_env(self, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ.get('PATH', '')}")
        env.update(extra)
        return env

    def session_args(self, output, extra=()):
        return ["--output", str(output),
                "--phoc", str(self.bin / "phoc"),
                "--gsettings", str(self.bin / "true"),
                "--cam-entry", str(self.bin / "cam-system-heap"),
                "--power-state", str(self.bin / "power-state.py"),
                "--magick", str(self.bin / "magick"),
                "--allow-existing-compositor",
                "--startup-timeout", "5", "--timeout", "30", *extra]

    def run_session(self, output, extra=(), env=None, wait=True):
        command = [sys.executable, "-c", BOOTSTRAP, str(SCRIPT),
                   *self.session_args(output, extra)]
        if wait:
            return subprocess.run(command, env=env or self.base_env(),
                                  capture_output=True, text=True, timeout=60)
        return subprocess.Popen(command, env=env or self.base_env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)

    def read_result(self, output):
        return json.loads((output / "result.json").read_text())

    def assert_process_gone(self, pid_path):
        pid = int(Path(pid_path).read_text())
        state = Path(f"/proc/{pid}/stat")
        deadline = time.monotonic() + 3
        while state.exists() and time.monotonic() < deadline:
            fields = state.read_text().rsplit(")", 1)[1].split()
            if fields[0] in {"Z", "X"}:
                break
            time.sleep(0.05)
        if state.exists():
            fields = state.read_text().rsplit(")", 1)[1].split()
            self.assertIn(fields[0], {"Z", "X"}, f"pid {pid} still live")


class QcamSessionTests(Base):
    def test_happy_path_starts_phoc_then_qcam_and_validates_jpeg(self):
        cam_args = self.root / "qcam-args"
        counts = self.root / "power-count"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_QCAM_ARGS=str(cam_args),
                              STUB_QCAM_PID=str(self.root / "qcam.pid"),
                              STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertIsNone(report["release_error"])
        self.assertEqual(report["geometry"], "JPEG 1280 960")
        self.assertEqual(report["remaining_processes"], [])
        self.assertTrue(Path(report["jpeg"]).is_file())
        tokens = cam_args.read_text().split()
        self.assertIn("-c", tokens)
        self.assertIn("-r", tokens)
        self.assertIn("qt", tokens)
        self.assertIn("--after-frames", tokens)
        self.assertIn("--output", tokens)
        self.assertIn("--stream=role=viewfinder,width=1280,height=960,pixelformat=RGB888",
                      tokens)
        self.assertEqual(counts.read_text(), "2")
        self.assert_process_gone(self.out / "runtime" / "phoc.pid")

    def test_sigterm_cancels_and_kills_owned_phoc_and_qcam(self):
        qcam_pid = self.root / "qcam-pid"
        counts = self.root / "power-count-cancel"
        process = self.run_session(
            self.out, ["--timeout", "60"],
            env=self.base_env(STUB_QCAM_PID=str(qcam_pid),
                              STUB_QCAM_DELAY="10",
                              STUB_POWER_COUNT=str(counts)),
            wait=False)
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not qcam_pid.exists():
                if process.poll() is not None:
                    self.fail("launcher exited before qcam started: "
                              + process.stdout.read())
                time.sleep(0.05)
            self.assertTrue(qcam_pid.exists(), "qcam never started")
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
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertEqual(report["remaining_processes"], [])
        self.assertEqual(counts.read_text(), "2")
        self.assert_process_gone(self.out / "runtime" / "phoc.pid")
        self.assert_process_gone(qcam_pid)

    def test_qcam_exit_without_jpeg_fails_after_release(self):
        counts = self.root / "power-count-nojpeg"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_NO_JPEG="1", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIn("JPEG", report["error"])
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertEqual(counts.read_text(), "2")
        self.assertEqual(report["remaining_processes"], [])

    def test_post_release_failure_fails_the_run(self):
        counts = self.root / "power-count-after"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_POWER_FAIL="after", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIs(report["camera_released"], False)
        self.assertIsNotNone(report["release_error"])
        self.assertEqual(counts.read_text(), "2")


if __name__ == "__main__":
    unittest.main()
