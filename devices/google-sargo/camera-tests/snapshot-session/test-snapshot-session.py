#!/usr/bin/env python3
"""Exercise the Snapshot session's subprocess, retry and cleanup behavior.

Everything runs with stub phoc/pipewire/wireplumber/pw-dump/snapshot/wtype/
power-state/magick (and a stub dbus-run-session) in a temporary directory. No
DRM, compositor, camera, gate or hardware is touched. run_session is run in a
real subprocess (bypassing only the root/preflight entry) so Unix-socket
readiness, JSON polling, retries, cancellation and process-group cleanup are
exercised for real.
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
SCRIPT = HERE / "snapshot-session.py"
CAMERA_NODE = "libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_0_camera_1a"

BOOTSTRAP = textwrap.dedent('''
    import sys
    from pathlib import Path
    import runpy
    m = runpy.run_path(sys.argv[1])
    parser = m["build_parser"]()
    args = parser.parse_args(sys.argv[2:])
    report = m["Reporter"](sys.stdout, Path(args.output) / "status")
    sys.exit(m["run_session"](args, report))
''')


def load_module():
    """Import the helper as a module (its main() is guarded)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pocketfed_snapshot_session", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sargo-snapshot-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.pid_dir = self.root / "pids"
        self.pid_dir.mkdir()
        self.counter = self.root / "shutter-count"
        self.out = self.root / "out"
        self.write_phoc()
        self.write_simple_daemon("pipewire")
        self.write_simple_daemon("wireplumber")
        self.write_pw_dump()
        self.write_snapshot()
        self.write_wtype()
        self.write_power_stub()
        self.write_magick_stub()
        self.write_dbus_stub()

    def write(self, name, body, python=True):
        path = self.bin / name
        path.write_text(("#!/usr/bin/env python3\n" + body) if python else body)
        path.chmod(0o755)
        return path

    def write_phoc(self):
        self.write("phoc", textwrap.dedent('''
            import os, socket, sys, time
            args = sys.argv[1:]
            runtime = os.environ["XDG_RUNTIME_DIR"]
            open(os.path.join(os.environ["STUB_PID_DIR"], "phoc.pid"), "w").write(
                str(os.getpid()))
            name = "pocketfed-snapshot"
            if "--socket" in args:
                name = args[args.index("--socket") + 1]
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(os.path.join(runtime, name))
            server.listen(1)
            time.sleep(3600)
        '''))

    def write_simple_daemon(self, name):
        self.write(name, textwrap.dedent('''
            import os, sys, time
            path = os.path.join(os.environ["STUB_PID_DIR"],
                                os.path.basename(sys.argv[0]) + ".pid")
            open(path, "w").write(str(os.getpid()))
            time.sleep(3600)
        '''))

    def write_pw_dump(self):
        self.write("pw-dump", textwrap.dedent('''
            import json, os, sys
            if os.environ.get("STUB_NODE") == "0":
                print("[]")
            else:
                name = os.environ.get("STUB_NODE_NAME", "libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_0_camera_1a")
                print(json.dumps([{
                    "id": 42,
                    "type": "PipeWire:Interface:Node",
                    "info": {"props": {"media.class": "Video/Source",
                                       "node.name": name}},
                }]))
            sys.exit(0)
        '''))

    def write_snapshot(self):
        self.write("snapshot", textwrap.dedent('''
            import os, sys, time
            home = os.environ["HOME"]
            camera = os.path.join(home, "Pictures", "Camera")
            os.makedirs(camera, exist_ok=True)
            open(os.path.join(os.environ["STUB_PID_DIR"], "snapshot.pid"), "w").write(
                str(os.getpid()))
            counter = os.environ.get("STUB_COUNTER", "")
            target = int(os.environ.get("STUB_JPEG_AFTER", "1"))
            width, height = 1280, 960
            frame = bytes([
                0xFF, 0xD8,
                0xFF, 0xC0, 0x00, 0x11, 0x08,
                (height >> 8) & 0xFF, height & 0xFF,
                (width >> 8) & 0xFF, width & 0xFF,
                0x03, 0x01, 0x11, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01,
                0xFF, 0xD9,
            ])
            written = False
            while True:
                if not written and counter and os.path.exists(counter):
                    try:
                        count = int(open(counter).read() or "0")
                    except ValueError:
                        count = 0
                    if count >= target:
                        path = os.path.join(
                            camera, "Photo from 2026-09-15 12-00-00.000000.jpeg")
                        with open(path, "wb") as handle:
                            handle.write(frame)
                        written = True
                time.sleep(0.05)
        '''))

    def write_wtype(self):
        self.write("wtype", textwrap.dedent('''
            import os, sys
            counter = os.environ.get("STUB_COUNTER")
            count = 0
            if counter and os.path.exists(counter):
                try:
                    count = int(open(counter).read() or "0")
                except (OSError, ValueError):
                    count = 0
            if counter:
                open(counter, "w").write(str(count + 1))
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

    def write_dbus_stub(self):
        # Keep the run hermetic: exec the wrapped command without a real bus.
        self.write("dbus-run-session", textwrap.dedent('''
            import os, sys
            args = sys.argv[1:]
            if args and args[0] == "--":
                args = args[1:]
            os.execvp(args[0], args)
        '''))

    def base_env(self, **extra):
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ.get('PATH', '')}")
        env["STUB_PID_DIR"] = str(self.pid_dir)
        env["STUB_COUNTER"] = str(self.counter)
        env.update(extra)
        return env

    def session_args(self, output, extra=()):
        return ["--output", str(output),
                "--phoc", str(self.bin / "phoc"),
                "--pipewire", str(self.bin / "pipewire"),
                "--wireplumber", str(self.bin / "wireplumber"),
                "--snapshot", str(self.bin / "snapshot"),
                "--wtype", str(self.bin / "wtype"),
                "--pw-dump", str(self.bin / "pw-dump"),
                "--power-state", str(self.bin / "power-state.py"),
                "--allow-existing-compositor",
                "--no-private-system-heap",
                "--settle", "0",
                "--retry-interval", "1",
                "--shutter-retries", "3",
                "--startup-timeout", "5",
                "--node-timeout", "5",
                "--timeout", "30",
                *extra]

    def run_session(self, output, extra=(), env=None, wait=True):
        command = [sys.executable, "-c", BOOTSTRAP, str(SCRIPT),
                   *self.session_args(output, extra)]
        if wait:
            return subprocess.run(command, env=env or self.base_env(),
                                  capture_output=True, text=True, timeout=90)
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

    def assert_all_gone(self):
        for name in ("phoc", "pipewire", "wireplumber", "snapshot"):
            pid_file = self.pid_dir / f"{name}.pid"
            if pid_file.exists():
                self.assert_process_gone(pid_file)


class SnapshotSessionTests(Base):
    def test_happy_path_waits_for_node_then_shutter_until_jpeg(self):
        counts = self.root / "power-count-happy"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_JPEG_AFTER="2", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertIsNone(report["release_error"])
        self.assertEqual(report["camera_node_id"], 42)
        self.assertEqual(report["camera_node_name"], CAMERA_NODE)
        self.assertEqual(report["geometry"], "JPEG 1280 960")
        self.assertEqual((report["width"], report["height"]), (1280, 960))
        self.assertEqual(report["geometry_method"], "magick")
        self.assertEqual(report["shutter_presses"], 2)
        self.assertTrue(report["dbus_run_session"])
        self.assertEqual(report["remaining_processes"], [])
        self.assertTrue(Path(report["photo"]).is_file())
        self.assertTrue(Path(report["source_jpeg"]).is_file())
        self.assertEqual(Path(report["photo"]).stat().st_mode & 0o777, 0o600)
        self.assertEqual(counts.read_text(), "2")
        self.assert_all_gone()

    def test_python_geometry_fallback_when_magick_absent(self):
        result = self.run_session(
            self.out,
            ["--magick", str(self.root / "missing-magick")],
            env=self.base_env(STUB_JPEG_AFTER="1"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["geometry"], "JPEG 1280 960")
        self.assertEqual(report["geometry_method"], "python")

    def test_camera_node_never_appears(self):
        counts = self.root / "power-count-nonode"
        result = self.run_session(
            self.out, ["--node-timeout", "2"],
            env=self.base_env(STUB_NODE="0", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIn("camera node", report["error"])
        self.assertTrue(report["camera_attempted"])
        self.assertIs(report["camera_released"], True)
        self.assertEqual(report["shutter_presses"], 0)
        self.assertIsNone(report["photo"])
        self.assertEqual(counts.read_text(), "2")
        self.assert_all_gone()

    def test_jpeg_never_appears_exhausts_retries(self):
        counts = self.root / "power-count-nojpeg"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_JPEG_AFTER="99", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIn("no JPEG", report["error"])
        self.assertEqual(report["shutter_presses"], 3)
        self.assertIs(report["camera_released"], True)
        self.assertEqual(report["remaining_processes"], [])
        self.assert_all_gone()

    def test_post_release_failure_fails_the_run(self):
        counts = self.root / "power-count-after"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_JPEG_AFTER="1", STUB_POWER_FAIL="after",
                              STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "failed")
        self.assertIs(report["camera_released"], False)
        self.assertIsNotNone(report["release_error"])
        self.assertEqual(counts.read_text(), "2")

    def test_sigterm_cancels_tears_down_and_runs_after_gate(self):
        counts = self.root / "power-count-cancel"
        process = self.run_session(
            self.out, ["--timeout", "60"],
            env=self.base_env(STUB_JPEG_AFTER="99", STUB_POWER_COUNT=str(counts)),
            wait=False)
        try:
            snapshot_pid = self.pid_dir / "snapshot.pid"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not snapshot_pid.exists():
                if process.poll() is not None:
                    self.fail("launcher exited before snapshot started: "
                              + process.stdout.read())
                time.sleep(0.05)
            self.assertTrue(snapshot_pid.exists(), "snapshot never started")
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
        self.assert_all_gone()

    def test_option_validation_rejects_bad_values(self):
        output = self.root / "cli-out"
        cases = [
            ["--output", str(output), "--softisp-mode", "bogus"],
            ["--output", str(output), "--settle", "-1"],
            ["--output", str(output), "--shutter-retries", "0"],
            ["--output", str(output), "--retry-interval", "0"],
            ["--output", str(output), "--startup-timeout", "0"],
            ["--output", str(output), "--node-timeout", "0"],
            ["--output", str(output), "--timeout", "0"],
            ["--output", str(output), "--socket", "bad name"],
            ["--output", str(output), "--camera-node", ""],
            ["--output", str(output), "--libcamera-log", "a b"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), *args],
                    env=self.base_env(), capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0,
                                    f"accepted invalid args: {args}")

    def test_no_dbus_skips_bus_and_sets_dead_address(self):
        counts = self.root / "power-count-nodbus"
        result = self.run_session(
            self.out, extra=("--no-dbus",),
            env=self.base_env(STUB_JPEG_AFTER="1", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["dbus_run_session"])
        self.assertEqual(report["shutter_presses"], 1)
        self.assert_all_gone()

    def test_wireplumber_rules_disable_front_camera_by_default(self):
        counts = self.root / "power-count-rules"
        result = self.run_session(
            self.out,
            env=self.base_env(STUB_JPEG_AFTER="1", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["disabled_nodes"],
                         ["libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_1_camera_1a"])
        self.assertFalse(report["private_system_heap"])
        rules = Path(report["wireplumber_rules"])
        self.assertTrue(rules.is_file())
        self.assertEqual(rules.stat().st_mode & 0o777, 0o600)
        text = rules.read_text()
        self.assertIn("monitor.libcamera.rules", text)
        self.assertIn('node.name = "libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_1_camera_1a"', text)
        self.assertIn("node.disabled = true", text)
        self.assertTrue(str(rules).startswith(str(self.out / "runtime" / "config")))
        self.assert_all_gone()

    def test_empty_disable_node_writes_no_rules(self):
        counts = self.root / "power-count-norules"
        result = self.run_session(
            self.out, extra=("--disable-node", ""),
            env=self.base_env(STUB_JPEG_AFTER="1", STUB_POWER_COUNT=str(counts)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.read_result(self.out)
        self.assertEqual(report["disabled_nodes"], [])
        self.assertIsNone(report["wireplumber_rules"])
        self.assert_all_gone()

    def test_system_heap_command_shape(self):
        module = load_module()
        command = module.system_heap_command(["wireplumber"], heap="/dev/null",
                                             unshare="/usr/bin/unshare")
        info = os.stat("/dev/null")
        self.assertEqual(command[:7], ["/usr/bin/unshare", "--mount", "--propagation",
                                       "private", "--", "sh", "-ec"])
        self.assertEqual(command[-3:], [str(os.major(info.st_rdev)),
                                        str(os.minor(info.st_rdev)), "wireplumber"])
        with self.assertRaises(module.SessionError):
            module.system_heap_command(["wireplumber"], heap=str(self.out))


if __name__ == "__main__":
    unittest.main()
