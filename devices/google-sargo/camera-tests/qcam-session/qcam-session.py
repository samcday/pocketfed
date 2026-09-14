#!/usr/bin/env python3
"""One bounded visible qcam session producing one auto-saved JPEG.

This is the post-readiness half of the libcamera-only Sargo trial. It is meant
to be the single command of ``wait-for-ready.py``: the gate first obtains a
fresh Volume Up authorization (and keeps monitoring Volume Down), then starts
this helper, which brings up a standalone Phoc session, runs the patched
``qcam`` through the existing private-system-heap wrapper, waits for qcam's
bounded one-shot save, strictly decodes the saved JPEG, and checks the camera
release gate.

It reuses the reviewed helpers in ``../libcamera-session/libcamera-session.py``
(``Reporter``, ``power_gate``, JPEG decode/identify, result writing and scoped
process-tree cleanup) instead of copying that framework. The only Phoc setup
reused from the archived Megapixels trial is the generic standalone compositor
start-up; none of that session's application, bus, cue or capture code is used.

Source-verified contract (libcamera 0.7.2, ``src/apps/qcam``)
-------------------------------------------------------------

- ``main.cpp`` parses ``-c/--camera``, ``-s/--stream`` and ``-r/--renderer``;
  the patched build also parses ``--output`` and ``--after-frames``.
- ``main_window.cpp`` resolves ``-c`` through ``CameraManager::get`` (an exact
  ``Camera::id()`` match) and, for a single stream, requires it to be the
  viewfinder role.
- The Qt viewfinder is the default renderer, and patch 0002 saves exactly one
  image from it after ``--after-frames`` rendered frames, then exits 0. A
  failed write exits nonzero; a missing/unknown option fails option parsing.
- qcam is a Wayland client, so a compositor and an XDG runtime directory must
  exist before it starts. Phoc is the installed standalone compositor.

The launcher does not start the camera before the gate authorizes it: the gate
owns that ordering, and this helper is only ever the gate's single command.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CAMERA_TESTS = HERE.parent
SESSION_HELPER = CAMERA_TESTS / "libcamera-session" / "libcamera-session.py"

# Importing the reviewed helper has no side effects: its main() is guarded by
# ``if __name__ == "__main__"``. Its functions are reused unchanged.
_SESSION_SPEC = importlib.util.spec_from_file_location(
    "pocketfed_libcamera_session", SESSION_HELPER)
session = importlib.util.module_from_spec(_SESSION_SPEC)
_SESSION_SPEC.loader.exec_module(session)

PREFIX = "pocketfed-qcam-session"
# Reporter.state() formats its module-level PREFIX; present this session's.
session.PREFIX = PREFIX

SessionError = session.SessionError
Cancelled = session.Cancelled
Reporter = session.Reporter
REAR = session.REAR
power_gate = session.power_gate
decode_file = session.decode_file
identify = session.identify
expected_geometry = session.expected_geometry
terminate_process_tree = session.terminate_process_tree
run_command = session.run_command
write_result = session.write_result

# Explicit viewfinder request; the stable rear id avoids the default front
# camera. ``cam`` adjusted RGB888 on device before; qcam geometry is what is
# asserted, not the negotiated pixel format.
DEFAULT_STREAM = "role=viewfinder,width=1280,height=960,pixelformat=RGB888"
DEFAULT_AFTER_FRAMES = 300  # roughly 10 s at 30 fps; a calibration sample
DEFAULT_SOCKET = "pocketfed-qcam"
DEFAULT_TIMEOUT = 90
DEFAULT_STARTUP_TIMEOUT = 20


def start_process(command, log_path, env):
    """Start an owned child in this process group and log it privately."""
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    stream = os.fdopen(descriptor, "w")
    process = subprocess.Popen(command, env=env, stdout=stream,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return process, stream


def close_streams(streams):
    for stream in streams:
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def refuse_existing_compositor():
    """Refuse to start when another compositor already owns the DRM seat."""
    running = []
    for path in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = path.read_text().strip()
        except OSError:
            continue
        if name in {"phoc", "phosh"}:
            running.append((path.parent.name, name))
    if running:
        detail = ", ".join(f"{name}({pid})" for pid, name in running)
        raise SessionError(f"existing compositor running: {detail}")


def wait_for_socket(path, process, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise SessionError(
                f"phoc exited with {process.returncode} before creating a socket")
        time.sleep(0.05)
    raise SessionError(f"phoc socket {path.name} did not appear within {timeout:g}s")


def session_env(runtime):
    """Standalone DRM session environment, private to this run's runtime dir."""
    env = dict(os.environ)
    env.update({
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_SESSION_TYPE": "wayland",
        "WLR_BACKENDS": "drm,libinput",
        "WLR_RENDERER": "gles2",
        "LIBSEAT_BACKEND": "noop",
    })
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "LD_PRELOAD", "QT_QPA_PLATFORM"):
        env.pop(key, None)
    return env


def qcam_env(runtime, socket):
    env = session_env(runtime)
    env["WAYLAND_DISPLAY"] = socket
    env["QT_QPA_PLATFORM"] = "wayland"
    return env


def best_effort(helper, reporter, argv, label):
    try:
        result = run_command([helper, *argv], timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        reporter.warn(f"{label}-failed {error}")
        return
    if result.returncode != 0:
        reporter.warn(f"{label}-failed exit-{result.returncode}")


def build_qcam_command(args, jpeg):
    # ``--tool qcam`` is cam-system-heap's explicit allowlist switch, not an
    # arbitrary command; the remaining tokens are the reviewed qcam options.
    return [str(args.cam_entry), "--tool", "qcam", "-c", args.camera,
            "-r", "qt", f"--stream={args.stream}",
            "--output", str(jpeg), "--after-frames", str(args.after_frames)]


def wait_child(process, timeout, grace=3.0):
    result = {"timed_out": False, "returncode": None}
    try:
        result["returncode"] = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
        try:
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            result["returncode"] = process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
    return result


def stop_children(processes):
    """Kill every owned child and report any process that survived."""
    remaining = []
    for process in processes:
        if process is None:
            continue
        remaining.extend(terminate_process_tree(process))
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    return sorted(set(remaining))


def run_session(args, reporter):
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    runtime = output / "runtime"
    runtime.mkdir(mode=0o700)
    jpeg = output / "frame.jpg"
    socket_path = runtime / args.socket

    report = {
        "status": "failed",
        "kernel": os.uname().release,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "camera": args.camera,
        "stream": args.stream,
        "after_frames": args.after_frames,
        "socket": args.socket,
        "jpeg": None,
        "geometry": None,
        "camera_attempted": False,
        "camera_released": None,
        "release_error": None,
        "phoc": None,
        "qcam": None,
        "remaining_processes": [],
        "error": None,
    }

    cleanup_started = False
    cancel_signum = None

    def handler(signum, _frame):
        nonlocal cancel_signum
        if cleanup_started:
            return
        cancel_signum = signum
        raise Cancelled(signum)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    status = None
    primary_error = None
    camera_attempted = False
    released = None
    release_error = None
    phoc = qcam = None
    phoc_stream = qcam_stream = None
    survivors = []

    try:
        reporter.state("preflight")
        if not os.access(args.phoc, os.X_OK):
            raise SessionError(f"phoc not executable: {args.phoc}")
        if not os.access(args.cam_entry, os.X_OK):
            raise SessionError(f"cam entry not executable: {args.cam_entry}")
        if not Path(args.power_state).is_file():
            raise SessionError(f"power-state helper missing: {args.power_state}")

        reporter.state("release-gate", "before")
        power_gate(Path(args.power_state), output / "power-before.json")

        if not args.allow_existing_compositor:
            refuse_existing_compositor()

        reporter.state("compositor-start", args.phoc)
        phoc, phoc_stream = start_process(
            [args.phoc, "--no-xwayland", "--socket", args.socket],
            output / "phoc.log", session_env(runtime))
        wait_for_socket(socket_path, phoc, args.startup_timeout)
        reporter.state("compositor-ready", args.socket)

        if args.gsettings:
            best_effort(args.gsettings, reporter,
                        ["set", "sm.puri.phoc", "auto-maximize", "true"],
                        "gsettings")

        reporter.state("capture", f"after-frames={args.after_frames}")
        camera_attempted = True
        report["camera_attempted"] = True
        qcam, qcam_stream = start_process(
            build_qcam_command(args, jpeg), output / "qcam.log",
            qcam_env(runtime, args.socket))
        result = wait_child(qcam, args.timeout)
        report["qcam"] = result
        if result["timed_out"] or result["returncode"] != 0:
            raise SessionError("qcam run failed or did not stop cleanly")

        if not jpeg.is_file() or jpeg.stat().st_size == 0:
            raise SessionError("qcam exited without saving a JPEG")
        # A non-empty file is not completion: decode every pixel, then confirm
        # the geometry matches the requested viewfinder.
        decode_file(args.magick, jpeg)
        geometry = identify(args.magick, jpeg)
        width, height = expected_geometry(args.stream)
        if geometry != f"JPEG {width} {height}":
            raise SessionError(f"unexpected JPEG geometry: {geometry}")

        report["jpeg"] = str(jpeg)
        report["geometry"] = geometry
        status = "passed"
    except Cancelled as cancel:
        cancel_signum = cancel.signum
        status = "cancelled"
        primary_error = f"signal {cancel.signum}"
        reporter.state("cancelled", f"signal-{cancel.signum}")
    except (SessionError, OSError) as error:
        status = "failed"
        primary_error = str(error)
        reporter.state("failed", str(error))
    finally:
        # Block further cancellation while cleaning up so repeated Volume Down
        # cannot skip the release gate or the result write.
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        cleanup_started = True
        try:
            survivors = stop_children([qcam, phoc])
            close_streams([qcam_stream, phoc_stream])
            report["remaining_processes"] = survivors
            if phoc is not None:
                report["phoc"] = phoc.returncode
            if camera_attempted:
                reporter.state("release-gate", "after")
                try:
                    power_gate(Path(args.power_state), output / "power-after.json")
                    released = True
                except (SessionError, OSError, subprocess.SubprocessError) as error:
                    released = False
                    release_error = str(error)
                    reporter.warn(f"post-release-gate-failed {release_error}")
            report["status"] = status or "failed"
            report["camera_released"] = released
            report["release_error"] = release_error
            if primary_error is not None:
                report["error"] = primary_error
            elif survivors:
                report["error"] = ("owned processes survived cleanup: "
                                   + ",".join(str(pid) for pid in survivors))
            elif release_error is not None:
                report["error"] = release_error
            if report["status"] == "passed" and released is not True:
                # Never return success without a confirmed release.
                report["status"] = "failed"
                report["error"] = release_error or "camera release unconfirmed"
            write_result(output / "result.json", report)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    if report["status"] == "passed":
        reporter.state("complete", report["jpeg"])
        return 0
    if report["status"] == "cancelled":
        return 130 if cancel_signum == signal.SIGINT else 143
    return 1


def _available(value):
    return shutil.which(value) is not None or Path(value).exists()


def preflight(args):
    missing = [name for name in
               (str(args.phoc), str(args.cam_entry), str(args.power_state), args.magick)
               if not _available(name)]
    if missing:
        raise SessionError("missing required tools: " + ", ".join(missing))


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh private directory for this session's output")
    parser.add_argument("--camera", default=REAR,
                        help="libcamera camera id (default: stable rear identity)")
    parser.add_argument("--stream", default=DEFAULT_STREAM,
                        help="qcam --stream value (default viewfinder 1280x960 RGB888)")
    parser.add_argument("--after-frames", type=int, default=DEFAULT_AFTER_FRAMES,
                        help="rendered viewfinder frames before the single save "
                             "(1..1800, default 300; a calibration sample)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="bound for the qcam run, seconds (1..300, default 90)")
    parser.add_argument("--startup-timeout", type=int, default=DEFAULT_STARTUP_TIMEOUT,
                        help="bound for the Phoc socket, seconds (1..120, default 20)")
    parser.add_argument("--socket", default=DEFAULT_SOCKET,
                        help="private Wayland socket name under the runtime dir")
    parser.add_argument("--phoc", default="phoc", help="Phoc compositor to start")
    parser.add_argument("--gsettings", default="gsettings",
                        help="best-effort auto-maximize helper (empty disables)")
    parser.add_argument("--cam-entry", type=Path,
                        default=CAMERA_TESTS / "cam-system-heap",
                        help="existing private-system-heap cam/qcam wrapper")
    parser.add_argument("--power-state", type=Path,
                        default=CAMERA_TESTS / "power-state.py")
    parser.add_argument("--magick", default="magick")
    parser.add_argument("--allow-existing-compositor", action="store_true",
                        help="do not refuse when phoc/phosh is already running")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 1 <= args.after_frames <= 1800:
        raise SystemExit("--after-frames must be 1..1800")
    if not 1 <= args.startup_timeout <= 120:
        raise SystemExit("--startup-timeout must be 1..120")
    if not 1 <= args.timeout <= 300:
        raise SystemExit("--timeout must be 1..300")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.socket):
        raise SystemExit("--socket must be a simple socket name")
    if os.geteuid() != 0:
        raise SystemExit("run as root for the private DMA-heap namespace and release gate")
    os.umask(0o077)
    try:
        preflight(args)
    except SessionError as error:
        print(f'{PREFIX}: failed "{error}"', file=sys.stderr)
        return 2
    if Path(args.output).exists():
        print(f'{PREFIX}: failed "output {args.output} already exists"',
              file=sys.stderr)
        return 2
    return run_session(args, Reporter(sys.stdout, Path(args.output) / "status"))


if __name__ == "__main__":
    raise SystemExit(main())
