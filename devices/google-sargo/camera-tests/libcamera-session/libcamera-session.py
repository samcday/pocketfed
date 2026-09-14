#!/usr/bin/env python3
"""One bounded libcamera capture session producing a settled RGB JPEG.

This is the libcamera-only replacement for the Megapixels trial session. It is
meant to be the single command of ``wait-for-ready.py``: the gate obtains a
fresh Volume Up authorization (and keeps monitoring Volume Down), then starts
this helper, which:

- passes the release gate before and after using the adjacent ``power-state.py``
- runs the existing private-system-heap ``cam-system-heap`` entry point once
- captures warm-up frames plus one final still in a single ``cam`` invocation
- prunes completed warm-up frames during the run so tmpfs holds only a few
- converts the final RGB frame to JPEG, strictly decodes both, records geometry
- retains the ``cam --metadata`` log and writes a private ``result.json``

Warm-up approach and its limit (no speculative architecture)
------------------------------------------------------------

The installed ``cam`` CLI (per the device's ``cam --help``) offers ``--capture
N`` and ``--file`` but no controls, no per-frame discard and no "save the last
frame" mode; ``python3-libcamera`` is not part of the installed
``libcamera``/``IPA``/``tools``/``GStreamer`` set, so ``cam --script`` is not
assumed. The simplest bounded, source-verifiable way to get a settled frame is
therefore a single ``cam`` run with ``--capture warmup+1`` while this helper
deletes completed warm-up frames as they appear. Only the final frame is
converted and kept.

This cannot prove AE/AF convergence by itself. If hardware trials show the last
of ``warmup+1`` frames is still not settled, the next step is a bounded
GStreamer ``libcamerasrc``/appsink helper that drops buffers without writing
files, or a libcamera Python script if ``python3-libcamera`` is added. That is
deliberately not implemented here.

``--display`` optionally forwards ``--display``/``--display=<connector>`` to
``cam`` for direct DRM/KMS preview on the phone; no desktop is constructed.
No options beyond those in the device's ``cam --help`` are invented.
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
import threading
import time


PREFIX = "pocketfed-libcamera-session"

REAR = "/base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a"
DEFAULT_STREAM = "role=still,width=1280,height=960,pixelformat=RGB888"

# Exactly the cam options named in the device's `cam --help`.
CAM_OPTIONS = ("--stream", "--capture", "--file", "--metadata", "--display")


class SessionError(RuntimeError):
    pass


class Cancelled(Exception):
    def __init__(self, signum):
        super().__init__(f"signal {signum}")
        self.signum = signum


class Reporter:
    def __init__(self, stream, status_file=None):
        self.stream = stream
        self.status_file = status_file

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


def group_members(pgid):
    members = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        try:
            if int(fields[2]) == pgid and fields[0] not in {"Z", "X"}:
                members.append(int(path.parent.name))
        except (IndexError, ValueError):
            continue
    return members


def child_pids(pid):
    children = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        try:
            if int(fields[1]) == pid and fields[0] not in {"Z", "X"}:
                children.append(int(path.parent.name))
        except (IndexError, ValueError):
            continue
    return children


def terminate_process_tree(process, grace=2.0):
    """Kill cam and its helpers without touching the gate.

    cam is started in this helper's own process group (the gate gave the helper
    a new session), so when this helper is the group leader every descendant is
    found by group membership; the gate kills that same group on Volume Down.
    """
    if process is None:
        return []
    if os.getpgrp() == os.getpid():
        def targets():
            return [pid for pid in group_members(os.getpgrp()) if pid != os.getpid()]
    else:
        def targets():
            return child_pids(process.pid)

    for signum in (signal.SIGTERM, signal.SIGKILL):
        current = targets()
        if not current:
            break
        for pid in current:
            try:
                os.kill(pid, signum)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + grace
        while targets() and time.monotonic() < deadline:
            time.sleep(0.05)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    return targets()


class FramePruner(threading.Thread):
    """Keep only the newest few completed frames so tmpfs stays bounded."""

    def __init__(self, directory, keep, interval=0.05):
        super().__init__(daemon=True)
        self.directory = directory
        self.keep = max(1, keep)
        self.interval = interval
        self.max_index = -1
        self._stop = threading.Event()

    def _frames(self):
        frames = []
        for path in self.directory.glob("frame-*.ppm"):
            match = re.fullmatch(r"frame-(\d+)\.ppm", path.name)
            if match:
                frames.append((int(match.group(1)), path))
        return sorted(frames)

    def prune(self):
        frames = self._frames()
        if frames:
            self.max_index = max(self.max_index, frames[-1][0])
        for _, path in frames[: -self.keep]:
            try:
                path.unlink()
            except OSError:
                pass

    def run(self):
        while not self._stop.is_set():
            self.prune()
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        self.join(timeout=2)
        self.prune()


def run_command(argv, env=None, timeout=30):
    return subprocess.run(argv, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout,
                          check=False)


def run_cam(command, log_path, timeout, directory, keep):
    result = {"timed_out": False, "returncode": None, "remaining": []}
    pruner = FramePruner(directory, keep)
    with log_path.open("w") as stream:
        # No start_new_session: cam stays inside the helper's group so the gate's
        # group cancellation reaches it, and terminate_process_tree can find it.
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
        pruner.start()
        try:
            try:
                result["returncode"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            result["remaining"] = terminate_process_tree(process)
            pruner.stop()
            result["max_index"] = pruner.max_index
    return result


def power_gate(power_state, output, timeout=10):
    result = subprocess.run(
        [sys.executable, str(power_state), "--require-released",
         "--timeout", str(timeout)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout + 10, check=False)
    output.write_text(result.stdout)
    if result.returncode:
        raise SessionError(f"camera release gate failed ({output.name})")


def convert_to_jpeg(magick, source, target, timeout=30):
    result = run_command([magick, str(source), str(target)], timeout=timeout)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SessionError(f"JPEG conversion failed: {result.stdout.strip()}")


def decode_file(magick, path, timeout=30):
    """Read every pixel, not just the container header."""
    result = run_command([magick, "-regard-warnings", str(path), "null:"],
                         timeout=timeout)
    if result.returncode != 0:
        raise SessionError(f"full decode failed for {path.name}: {result.stdout.strip()}")


def identify(magick, path, timeout=10):
    result = run_command([magick, "identify", "-format", "%m %w %h", str(path)],
                         timeout=timeout)
    if result.returncode != 0:
        raise SessionError(f"identify failed for {path.name}: {result.stdout.strip()}")
    return result.stdout.strip()


def expected_geometry(stream):
    width = re.search(r"width=(\d+)", stream)
    height = re.search(r"height=(\d+)", stream)
    if not (width and height):
        raise SessionError("--stream must include width and height")
    return int(width.group(1)), int(height.group(1))


def build_cam_command(args, total, pattern):
    command = [str(args.cam_entry), "-c", args.camera,
               f"--stream={args.stream}", f"--capture={total}",
               "--metadata", f"--file={pattern}"]
    if args.display is not None:
        command.append("--display" if args.display == "" else f"--display={args.display}")
    return command


def newest_frame(directory):
    frames = []
    for path in directory.glob("frame-*.ppm"):
        match = re.fullmatch(r"frame-(\d+)\.ppm", path.name)
        if match:
            frames.append((int(match.group(1)), path))
    if not frames:
        return None
    return max(frames)[1]


def write_result(path, report):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def run_session(args, reporter):
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "status": "failed",
        "kernel": os.uname().release,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "camera": args.camera,
        "stream": args.stream,
        "warmup": args.warmup,
        "capture_total": args.warmup + 1,
        "display": args.display,
        "jpeg": None,
        "geometry": None,
        "metadata_log": str(output / "cam.log"),
        "error": None,
    }

    def handler(signum, _frame):
        raise Cancelled(signum)

    previous_term = signal.signal(signal.SIGTERM, handler)
    previous_int = signal.signal(signal.SIGINT, handler)
    try:
        reporter.state("preflight")
        if not os.access(args.cam_entry, os.X_OK):
            raise SessionError(f"cam entry not executable: {args.cam_entry}")
        if not Path(args.power_state).is_file():
            raise SessionError(f"power-state helper missing: {args.power_state}")
        reporter.state("release-gate", "before")
        power_gate(Path(args.power_state), output / "power-before.json")
        total = args.warmup + 1
        pattern = str(output / "frame-#.ppm")
        command = build_cam_command(args, total, pattern)
        reporter.state("capture", f"warmup={args.warmup} final=1")
        cam = run_cam(command, output / "cam.log", args.timeout, output, args.keep)
        report["cam"] = cam
        if cam["timed_out"] or cam["returncode"] != 0 or cam["remaining"]:
            raise SessionError("cam run failed or did not stop cleanly")
        if cam["max_index"] + 1 < total:
            raise SessionError(
                f"cam produced {cam['max_index'] + 1} frames, expected {total} warm-up+final")
        final = newest_frame(output)
        if final is None:
            raise SessionError("no final RGB frame was saved")
        width, height = expected_geometry(args.stream)
        ppm_geometry = identify(args.magick, final)
        if ppm_geometry != f"PPM {width} {height}":
            raise SessionError(f"unexpected final frame geometry: {ppm_geometry}")
        decode_file(args.magick, final)
        jpeg = output / "final.jpg"
        convert_to_jpeg(args.magick, final, jpeg)
        decode_file(args.magick, jpeg)
        jpeg_geometry = identify(args.magick, jpeg)
        if not jpeg_geometry.startswith(f"JPEG {width} {height}"):
            raise SessionError(f"unexpected JPEG geometry: {jpeg_geometry}")
        report["jpeg"] = str(jpeg)
        report["geometry"] = jpeg_geometry
        report["frame_bytes"] = final.stat().st_size
        reporter.state("release-gate", "after")
        power_gate(Path(args.power_state), output / "power-after.json")
        report["status"] = "passed"
        reporter.state("complete", str(jpeg))
        return 0
    except Cancelled as cancel:
        report["status"] = "cancelled"
        report["error"] = f"signal {cancel.signum}"
        reporter.state("cancelled", f"signal-{cancel.signum}")
        return 130 if cancel.signum == signal.SIGINT else 143
    except (SessionError, OSError) as error:
        report["error"] = str(error)
        reporter.state("failed", str(error))
        return 1
    finally:
        write_result(output / "result.json", report)
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def preflight(args):
    missing = []
    if not Path(args.cam_entry).exists():
        missing.append(str(args.cam_entry))
    if not Path(args.power_state).is_file():
        missing.append(str(args.power_state))
    for name in ("magick",):
        if shutil.which(getattr(args, name)) is None:
            missing.append(name)
    if missing:
        raise SessionError("missing required tools: " + ", ".join(missing))


def build_parser(default_dir):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh private directory for this session's output")
    parser.add_argument("--camera", default=REAR)
    parser.add_argument("--stream", default=DEFAULT_STREAM)
    parser.add_argument("--warmup", type=int, default=4,
                        help="discarded warm-up frames before the final still (default 4)")
    parser.add_argument("--keep", type=int, default=2,
                        help="completed frames kept on disk during the run (default 2)")
    parser.add_argument("--timeout", type=int, default=60,
                        help="bound for the whole cam run, seconds (default 60)")
    parser.add_argument("--display", nargs="?", const="", default=None,
                        help="forward cam --display[=<connector>] (DRM/KMS preview)")
    parser.add_argument("--cam-entry", type=Path,
                        default=default_dir / "cam-system-heap",
                        help="existing private-system-heap cam wrapper")
    parser.add_argument("--power-state", type=Path,
                        default=default_dir / "power-state.py")
    parser.add_argument("--magick", default="magick")
    return parser


def main(argv=None):
    default_dir = Path(__file__).resolve().parent.parent
    args = build_parser(default_dir).parse_args(argv)
    if not 1 <= args.warmup <= 30:
        raise SystemExit("--warmup must be 1..30")
    if not 1 <= args.keep <= 30:
        raise SystemExit("--keep must be 1..30")
    if not 1 <= args.timeout <= 300:
        raise SystemExit("--timeout must be 1..300")
    if os.geteuid() != 0:
        raise SystemExit("run as root for the private DMA-heap namespace and release gate")
    os.umask(0o077)
    try:
        preflight(args)
    except SessionError as error:
        print(f'{PREFIX}: failed "{error}"', file=sys.stderr)
        return 2
    if Path(args.output).exists():
        print(f'{PREFIX}: failed "output {args.output} already exists"', file=sys.stderr)
        return 2
    return run_session(args, Reporter(sys.stdout, Path(args.output) / "status"))


if __name__ == "__main__":
    raise SystemExit(main())
