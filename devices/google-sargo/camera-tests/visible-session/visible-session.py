#!/usr/bin/env python3
"""Run one visible Megapixels preview+capture session on the phone's display.

This is the post-readiness half of a Sargo camera trial. It is meant to be run
as the single command of ``wait-for-ready.py``: the gate first obtains a fresh
Volume Up authorization (and keeps monitoring Volume Down), then starts this
program, which brings up a real DRM-backed Phoc session, shows an active
Megapixels preview, waits a short settling interval, runs any configured
control commands, and triggers exactly one capture.

Design notes (see README.md for the full rationale):

- Compositor: the installed ``phoc`` (0.56) running standalone. ``man phoc``
  states it "works perfectly fine on its own"; ``-S`` is only for attaching a
  shell, which this session deliberately does not do. Cage is not part of the
  device image, so Phoc is the smallest credible installed choice.
- Display: ``WLR_BACKENDS=drm`` on a dedicated VT (set by the systemd unit).
  ``LIBSEAT_BACKEND=noop`` lets root open DRM/input directly without a logind
  session; the README documents the greetd/logind alternative.
- Session bus: the outer invocation re-executes itself under
  ``dbus-run-session`` so Phoc, Megapixels and this driver share one private
  session bus. Nothing outside the private runtime directory is touched.
- Cues: on-screen preview is the primary cue; ``fbcli`` (feedbackd) provides
  an existing haptic/audible focus and shutter cue and is best-effort.
- Manual focus/exposure is done by the operator on the visible UI during the
  preview interval, or with ``--control-command`` once exact actions are known.

This program never reads or writes GPIO and never touches
``/sys/kernel/debug/gpio``. Capture output and status files stay private.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


PREFIX = "pocketfed-camera-visible"

DEFAULT_APP_NAME = "me.gapixels.Megapixels"
DEFAULT_OBJECT_PATH = "/me/gapixels/Megapixels"
ACTION_INTERFACE = "org.gtk.Actions"


class SessionError(RuntimeError):
    pass


class Cancelled(Exception):
    def __init__(self, signum):
        super().__init__(f"signal {signum}")
        self.signum = signum


class Reporter:
    def __init__(self, stream, status_file=None, quiet=False):
        self.stream = stream
        self.status_file = Path(status_file) if status_file else None
        self.quiet = quiet

    @staticmethod
    def _clean(text, limit=200):
        return " ".join(str(text).split())[:limit]

    def state(self, state, detail=""):
        line = f"{PREFIX}: state={state}"
        detail = self._clean(detail)
        if detail:
            line += f' detail="{detail}"'
        print(line, file=self.stream, flush=True)
        if self.status_file is not None:
            try:
                self._write_status(line)
            except OSError:
                pass

    def warn(self, message):
        print(f'{PREFIX}: warn="{self._clean(message)}"', file=self.stream, flush=True)

    def _write_status(self, line):
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_name(self.status_file.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, (line + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        os.replace(temporary, self.status_file)


def _signal_process_group(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def start_process(argv, env, log_path):
    stream = subprocess.DEVNULL
    if log_path is not None:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        stream = os.fdopen(descriptor, "w")
    process = subprocess.Popen(argv, env=env, stdout=stream,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               start_new_session=True)
    return process, stream


def stop_process(process, grace=2.0):
    if process is None or process.poll() is not None:
        return
    _signal_process_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_process_group(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def run_command(argv, env, timeout):
    return subprocess.run(argv, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout,
                          check=False)


def run_shell(shell, command, env, timeout):
    return subprocess.run([shell, "-c", command],
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, timeout=timeout, check=False)


def gdbus_activate(args, action):
    return [args.gdbus, "call", "--session", "--dest", args.app_name,
            "--object-path", args.object_path, "--method",
            f"{ACTION_INTERFACE}.Activate", action, "[]", "{}"]


def session_env(args, output, runtime):
    env = dict(os.environ)
    env.update({
        "HOME": str(output / "home"),
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_CONFIG_HOME": str(output / "config"),
        "XDG_CACHE_HOME": str(output / "cache"),
        "XDG_DATA_HOME": str(output / "data"),
        "XDG_STATE_HOME": str(output / "state"),
        "XDG_PICTURES_DIR": str(output / "pictures"),
        "XDG_SESSION_TYPE": "wayland",
        "WLR_BACKENDS": args.wlr_backends,
        "WLR_RENDERER": args.wlr_renderer,
        "LIBSEAT_BACKEND": args.libseat_backend,
        "POCKETFED_VISIBLE_SOCKET": args.socket,
    })
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "LD_PRELOAD"):
        env.pop(key, None)
    return env


def compositor_env(args, output, runtime):
    return session_env(args, output, runtime)


def application_env(args, output, runtime):
    env = session_env(args, output, runtime)
    env["WAYLAND_DISPLAY"] = args.socket
    env["GDK_BACKEND"] = "wayland"
    return env


def refuse_existing_compositor():
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


def wait_for_socket(path, compositor, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if compositor.poll() is not None:
            raise SessionError(
                f"phoc exited with {compositor.returncode} before creating a socket")
        time.sleep(0.05)
    raise SessionError(f"phoc socket {path.name} did not appear within {timeout:g}s")


def wait_for_app(args, app, env, reporter):
    try:
        result = run_command(
            [args.gdbus, "wait", "--session", "--timeout", str(args.startup_timeout),
             args.app_name], env, args.startup_timeout + 5)
    except subprocess.TimeoutExpired:
        result = None
    if result is not None and result.returncode == 0:
        return
    if app.poll() is not None:
        raise SessionError(f"{args.app} exited with {app.returncode} before becoming ready")
    output = result.stdout.strip() if result is not None else "gdbus wait timed out"
    raise SessionError(f"{args.app_name} did not appear on the session bus: {output}")


def interruptible_sleep(seconds, processes):
    deadline = time.monotonic() + seconds
    while True:
        for process in processes:
            if process.poll() is not None:
                raise SessionError(f"process exited with {process.returncode} during preview")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.1, remaining))


def wait_for_jpeg(pictures, before, timeout):
    deadline = time.monotonic() + timeout
    stable = None
    stable_since = None
    while time.monotonic() < deadline:
        candidates = sorted(path for path in pictures.glob("*.jpg")
                            if path.name not in before)
        if candidates:
            candidate = candidates[-1]
            stat = candidate.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature != stable:
                stable, stable_since = signature, time.monotonic()
            elif time.monotonic() - stable_since >= 0.5 and stat.st_size > 0:
                return candidate
        time.sleep(0.1)
    raise SessionError("no completed JPEG appeared after the capture action")


def cue(args, command, env, reporter, label):
    if not command:
        return
    try:
        result = run_shell(args.shell, command, env, 3)
    except (OSError, subprocess.SubprocessError) as error:
        reporter.warn(f"{label}-failed {error}")
        return
    if result.returncode != 0:
        reporter.warn(f"{label}-failed exit-{result.returncode}")


def verify_jpeg(args, jpeg, env, reporter):
    if not args.verify_jpeg:
        return
    if shutil.which(args.magick) is None:
        reporter.warn(f"verify-jpeg-skipped {args.magick} not found")
        return
    try:
        result = run_command([args.magick, "-regard-warnings", str(jpeg), "null:"],
                             env, 30)
    except (OSError, subprocess.SubprocessError) as error:
        raise SessionError(f"JPEG validation failed: {error}")
    if result.returncode != 0:
        raise SessionError(f"JPEG validation failed: {result.stdout.strip()}")


def capture_once(args, pictures, env, reporter):
    before = {path.name for path in pictures.glob("*.jpg")}
    result = run_command(gdbus_activate(args, args.capture_action), env,
                         args.capture_timeout)
    if result.returncode != 0:
        raise SessionError(f"capture action failed: {result.stdout.strip()}")
    jpeg = wait_for_jpeg(pictures, before, args.capture_timeout)
    verify_jpeg(args, jpeg, env, reporter)
    return jpeg


def write_result(path, report):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def run_inner(args, reporter):
    output = Path(args.output).resolve()
    runtime = output / "runtime"
    pictures = output / "pictures"
    for directory in (output, runtime, pictures, output / "home", output / "config",
                      output / "cache", output / "data", output / "state"):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    compositor = app = None
    report = {
        "status": "failed",
        "kernel": os.uname().release,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "socket": args.socket,
        "preview_seconds": args.preview_seconds,
        "capture_action": args.capture_action,
        "capture": None,
        "error": None,
    }

    def handler(signum, _frame):
        raise Cancelled(signum)

    previous = signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    try:
        if not args.allow_existing_compositor:
            refuse_existing_compositor()
        env = compositor_env(args, output, runtime)
        app_env = application_env(args, output, runtime)
        reporter.state("compositor-start", "phoc")
        _best_effort(args, reporter, env, [args.gsettings, "set",
                                           "sm.puri.phoc", "auto-maximize", "true"],
                     "gsettings")
        compositor, _ = start_process(
            [args.phoc, "--no-xwayland", "--socket", args.socket], env,
            output / "phoc.log")
        wait_for_socket(runtime / args.socket, compositor, args.startup_timeout)
        reporter.state("compositor-ready", args.socket)
        reporter.state("app-start", args.app)
        app, _ = start_process([args.app], app_env, output / "app.log")
        wait_for_app(args, app, app_env, reporter)
        reporter.state("app-ready", args.app_name)
        cue(args, args.focus_cue, app_env, reporter, "focus-cue")
        reporter.state("preview", f"{args.preview_seconds:g}s")
        interruptible_sleep(args.preview_seconds, [compositor, app])
        for command in args.control_command:
            reporter.state("control", command)
            result = run_shell(args.shell, command, app_env, args.control_timeout)
            if result.returncode != 0:
                raise SessionError(f"control command failed: {command}")
        reporter.state("capture", args.capture_action)
        cue(args, args.capture_cue, app_env, reporter, "capture-cue")
        jpeg = capture_once(args, pictures, app_env, reporter)
        report["capture"] = str(jpeg)
        reporter.state("quit", args.quit_action)
        try:
            run_command(gdbus_activate(args, args.quit_action), app_env, 5)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            app.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        report["status"] = "passed"
        reporter.state("complete", str(jpeg))
        return 0
    except Cancelled as cancel:
        report["status"] = "cancelled"
        report["error"] = f"signal {cancel.signum}"
        reporter.state("cancelled", f"signal-{cancel.signum}")
        return 130 if cancel.signum == signal.SIGINT else 143
    except SessionError as error:
        report["error"] = str(error)
        reporter.state("failed", str(error))
        return 1
    except OSError as error:
        report["error"] = str(error)
        reporter.state("failed", str(error))
        return 1
    finally:
        stop_process(app)
        stop_process(compositor)
        report["phoc_exit"] = None if compositor is None else compositor.returncode
        report["app_exit"] = None if app is None else app.returncode
        write_result(output / "result.json", report)
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def _best_effort(args, reporter, env, argv, label):
    try:
        result = run_command(argv, env, 5)
    except (OSError, subprocess.SubprocessError) as error:
        reporter.warn(f"{label}-failed {error}")
        return
    if result.returncode != 0:
        reporter.warn(f"{label}-failed exit-{result.returncode} {result.stdout.strip()}")


def preflight(args):
    required = {
        "phoc": args.phoc,
        "app": args.app,
        "gdbus": args.gdbus,
        "bus-runner": args.bus_runner,
        "shell": args.shell,
    }
    missing = [name for name, path in required.items()
               if shutil.which(path) is None and not Path(path).exists()]
    if missing:
        raise SessionError("missing required commands: " + ", ".join(missing))


def plan(args):
    return {
        "phoc": [args.phoc, "--no-xwayland", "--socket", args.socket],
        "app": [args.app],
        "capture": gdbus_activate(args, args.capture_action),
        "cue": {"focus": args.focus_cue, "capture": args.capture_cue},
        "control": args.control_command,
        "output": str(Path(args.output).resolve()),
        "gate": ("wait-for-ready.py --settle <s> --timeout <t> -- "
                 "visible-session.py --output " + str(Path(args.output).resolve())),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh private directory for session output")
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true",
                        help="validate tools and print the plan without starting a session")
    parser.add_argument("--phoc", default="phoc")
    parser.add_argument("--app", default="megapixels")
    parser.add_argument("--gdbus", default="gdbus")
    parser.add_argument("--gsettings", default="gsettings")
    parser.add_argument("--magick", default="magick")
    parser.add_argument("--bus-runner", default="dbus-run-session")
    parser.add_argument("--shell", default="sh")
    parser.add_argument("--socket", default="pocketfed-camera-visible")
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--object-path", default=DEFAULT_OBJECT_PATH)
    parser.add_argument("--capture-action", default="capture")
    parser.add_argument("--quit-action", default="quit")
    parser.add_argument("--preview-seconds", type=float, default=10.0)
    parser.add_argument("--capture-timeout", type=float, default=60.0)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--control-timeout", type=float, default=15.0)
    parser.add_argument("--control-command", action="append", default=[],
                        help="shell command run after preview settling, before capture")
    parser.add_argument("--focus-cue", default="fbcli -E camera-focus",
                        help="existing-UI cue run before the preview (empty to disable)")
    parser.add_argument("--capture-cue", default="fbcli -E camera-shutter",
                        help="existing-UI cue run just before capture (empty to disable)")
    parser.add_argument("--verify-jpeg", action="store_true",
                        help="decode the saved JPEG with ImageMagick")
    parser.add_argument("--allow-existing-compositor", action="store_true",
                        help="do not refuse when phoc/phosh is already running")
    parser.add_argument("--wlr-backends", default="drm")
    parser.add_argument("--wlr-renderer", default="gles2")
    parser.add_argument("--libseat-backend", default="noop",
                        help="libseat backend for standalone root DRM (default noop)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 0 <= args.preview_seconds <= 300:
        raise SystemExit("--preview-seconds must be 0..300")
    if not 1 <= args.capture_timeout <= 600:
        raise SystemExit("--capture-timeout must be 1..600")
    if not 1 <= args.startup_timeout <= 120:
        raise SystemExit("--startup-timeout must be 1..120")
    if not 1 <= args.control_timeout <= 120:
        raise SystemExit("--control-timeout must be 1..120")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.socket):
        raise SystemExit("--socket must be a simple socket name")
    if args.inner:
        reporter = Reporter(sys.stdout, status_file=Path(args.output) / "status")
        return run_inner(args, reporter)
    output = Path(args.output).resolve()
    try:
        preflight(args)
    except SessionError as error:
        print(f"{PREFIX}: failed \"{error}\"", file=sys.stderr)
        return 2
    if args.check:
        print(json.dumps(plan(args), indent=2))
        return 0
    if output.exists():
        print(f"{PREFIX}: failed \"output {output} already exists\"", file=sys.stderr)
        return 2
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    runtime = output / "runtime"
    runtime.mkdir(mode=0o700)
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime))
    inner = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--inner"]
    try:
        return subprocess.run([args.bus_runner, "--", *inner], env=env).returncode
    except OSError as error:
        print(f"{PREFIX}: failed \"cannot start {args.bus_runner}: {error}\"",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
