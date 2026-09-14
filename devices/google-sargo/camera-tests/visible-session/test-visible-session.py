#!/usr/bin/env python3
"""Exercise the visible session's subprocess and cleanup behavior.

Everything here runs with stub phoc/app/gdbus tools in a temporary directory;
no DRM device, compositor, camera, session bus, SSH or network is touched.
"""

import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "visible-session.py"
UNIT = HERE / "pocketfed-camera-visible.service"


class VisibleSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sargo-visible-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.write_stub("phoc", textwrap.dedent('''
            import os, time
            runtime = os.environ["XDG_RUNTIME_DIR"]
            os.makedirs(runtime, exist_ok=True)
            open(os.path.join(runtime, "phoc.pid"), "w").write(str(os.getpid()))
            open(os.path.join(runtime, os.environ["POCKETFED_VISIBLE_SOCKET"]), "w").close()
            time.sleep(3600)
        '''))
        self.write_stub("phoc_fail", "import sys; sys.exit(3)\n")
        self.write_stub("app", textwrap.dedent('''
            import os, time
            runtime = os.environ["XDG_RUNTIME_DIR"]
            open(os.path.join(runtime, "app.pid"), "w").write(str(os.getpid()))
            while not os.path.exists(os.path.join(runtime, "app.quit")):
                time.sleep(0.05)
        '''))
        self.write_stub("gdbus", textwrap.dedent('''
            import os, sys
            args = sys.argv[1:]
            sequence = os.environ.get("STUB_SEQUENCE")
            if "wait" in args:
                sys.exit(0)
            action = None
            if "--method" in args:
                index = args.index("--method")
                action = args[index + 2] if index + 2 < len(args) else None
            if sequence:
                open(sequence, "a").write((action or "?") + "\\n")
            runtime = os.environ["XDG_RUNTIME_DIR"]
            if action == "capture" and not os.environ.get("STUB_NO_JPEG"):
                pictures = os.environ["XDG_PICTURES_DIR"]
                os.makedirs(pictures, exist_ok=True)
                open(os.path.join(pictures, "shot.jpg"), "wb").write(
                    b"\\xff\\xd8\\xff" + b"0" * 64)
            if action == "quit":
                open(os.path.join(runtime, "app.quit"), "w").close()
            sys.exit(0)
        '''))
        self.write_stub("true", "#!/bin/sh\nexit 0\n", python=False)

    def write_stub(self, name, body, python=True):
        path = self.bin / name
        if python:
            path.write_text("#!/usr/bin/env python3\n" + body)
        else:
            path.write_text(body)
        path.chmod(0o755)
        return path

    def base_env(self, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ.get('PATH', '')}")
        env.update(extra)
        return env

    def inner_command(self, output, extra=()):
        return [sys.executable, str(SCRIPT), "--inner", "--output", str(output),
                "--allow-existing-compositor", "--phoc", str(self.bin / "phoc"),
                "--app", str(self.bin / "app"), "--gdbus", str(self.bin / "gdbus"),
                "--gsettings", str(self.bin / "true"), "--bus-runner", str(self.bin / "true"),
                "--focus-cue", "", "--capture-cue", "", "--startup-timeout", "5",
                *extra]

    def run_inner(self, output, extra=(), env=None):
        return subprocess.run(self.inner_command(output, extra),
                              env=env or self.base_env(), capture_output=True,
                              text=True, timeout=60)

    def assert_processes_gone(self, output):
        runtime = Path(output) / "runtime"
        for name in ("phoc.pid", "app.pid"):
            path = runtime / name
            if not path.exists():
                continue
            pid = int(path.read_text())
            deadline = time.monotonic() + 3
            state = Path(f"/proc/{pid}/stat")
            while state.exists() and time.monotonic() < deadline:
                fields = state.read_text().rsplit(")", 1)[1].split()
                if fields[0] in {"Z", "X"}:
                    break
                time.sleep(0.05)
            if state.exists():
                fields = state.read_text().rsplit(")", 1)[1].split()
                self.assertIn(fields[0], {"Z", "X"}, f"{name} {pid} still live")

    def test_happy_path_runs_one_capture_then_quits(self):
        output = self.root / "out-happy"
        sequence = self.root / "seq"
        result = self.run_inner(output, ["--preview-seconds", "0",
                                         "--capture-timeout", "5"],
                                env=self.base_env(STUB_SEQUENCE=str(sequence)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sequence.read_text().split(), ["capture", "quit"])
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["status"], "passed")
        self.assertTrue(Path(report["capture"]).is_file())
        self.assert_processes_gone(output)

    def test_control_commands_run_before_capture(self):
        output = self.root / "out-control"
        sequence = self.root / "seq-control"
        command = 'printf "control\\n" >> "$STUB_SEQUENCE"'
        result = self.run_inner(output, ["--preview-seconds", "0",
                                         "--capture-timeout", "5",
                                         "--control-command", command],
                                env=self.base_env(STUB_SEQUENCE=str(sequence)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sequence.read_text().split(), ["control", "capture", "quit"])

    def test_capture_timeout_without_jpeg_fails_and_cleans_up(self):
        output = self.root / "out-timeout"
        result = self.run_inner(output, ["--preview-seconds", "0",
                                         "--capture-timeout", "1"],
                                env=self.base_env(STUB_NO_JPEG="1"))
        self.assertEqual(result.returncode, 1)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIn("JPEG", report["error"])
        self.assert_processes_gone(output)

    def test_phoc_exit_before_socket_fails_without_starting_app(self):
        output = self.root / "out-phocfail"
        command = self.inner_command(output, ["--preview-seconds", "0"])
        index = command.index(str(self.bin / "phoc"))
        command[index] = str(self.bin / "phoc_fail")
        result = subprocess.run(command, env=self.base_env(), capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertIn("phoc", report["error"])
        self.assertFalse((output / "runtime" / "app.pid").exists())

    def test_sigterm_during_preview_cancels_and_stops_children(self):
        output = self.root / "out-cancel"
        process = subprocess.Popen(
            self.inner_command(output, ["--preview-seconds", "30"]),
            env=self.base_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True)
        try:
            status = output / "status"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if status.exists() and "state=preview" in status.read_text():
                    break
                if process.poll() is not None:
                    self.fail("session exited before preview: "
                              + process.stdout.read())
                time.sleep(0.05)
            else:
                self.fail("preview did not start")
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
        self.assertEqual(process.returncode, 143)
        report = json.loads((output / "result.json").read_text())
        self.assertEqual(report["status"], "cancelled")
        self.assert_processes_gone(output)

    def test_check_prints_plan_without_creating_output(self):
        output = self.root / "out-check"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(output),
             "--app", str(self.bin / "app"), "--phoc", str(self.bin / "phoc"),
             "--check"],
            env=self.base_env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["app"], [str(self.bin / "app")])
        self.assertFalse(output.exists())

    def test_missing_phoc_fails_preflight_before_creating_output(self):
        output = self.root / "out-missing"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(output),
             "--app", str(self.bin / "app"), "--phoc", "/nonexistent/phoc",
             "--bus-runner", str(self.bin / "true"), "--shell", "sh"],
            env=self.base_env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())


class UnitWiringTests(unittest.TestCase):
    def test_unit_gates_before_starting_the_session(self):
        text = UNIT.read_text()
        self.assertIn("wait-for-ready.py", text)
        self.assertIn("visible-session.py", text)
        self.assertLess(text.index("wait-for-ready.py"), text.index("visible-session.py"))
        self.assertIn(" -- ", text)
        self.assertIn("TTYPath=", text)
        self.assertEqual(stat.S_IMODE(UNIT.stat().st_mode) & 0o111, 0,
                         "a systemd unit file should not be executable")

    def test_unit_is_private_and_bounded(self):
        text = UNIT.read_text()
        self.assertIn("StandardInput=tty", text)
        self.assertIn("LIBSEAT_BACKEND=noop", text)
        self.assertIn("TimeoutStopSec=", text)


if __name__ == "__main__":
    unittest.main()
