#!/usr/bin/env python3
"""One bounded libcamera capture session producing a final-frame JPEG.

This is the libcamera-only replacement for the Megapixels trial session and is
meant to be the single command of ``wait-for-ready.py``: the gate obtains a
fresh Volume Up authorization (and keeps monitoring Volume Down), then starts
this helper. It runs the existing private-system-heap ``cam-system-heap`` entry
point once, keeps the final captured frame, converts it to JPEG, strictly
decodes it, and retains the ``cam --metadata`` log.

Source-verified contract (libcamera 0.7.2, src/apps/cam)
--------------------------------------------------------

- ``camera_session.cpp`` rejects ``--display`` together with ``--file`` and
  requires a single viewfinder stream for ``--display``. A file-producing run
  therefore cannot show preview; on-screen UI acceptance stays pending.
- ``file_sink.cpp`` expands the first ``#`` in ``--file`` to
  ``<streamName>-<frame sequence>`` (e.g. ``cam0-stream0-000123``), so a
  numbered pattern does not match a simple ``frame-<digits>`` name.
- ``PPMWriter`` opens the output with ``std::ofstream(filename, std::ios::binary)``,
  which truncates. A fixed ``.ppm`` name is therefore overwritten by every
  frame and holds the final frame after the run; no warm-up pruning is needed.
- ``camera_session.cpp`` prints one ``... <stream> seq: <digits> bytesused: ...``
  line per completed request, and with ``--metadata`` follows it with
  tab-indented ``Control = value`` lines. The completed-frame count is verified
  from those ``seq:`` lines.
- ``--script`` is a YAML capture-session config (``capture_script.cpp``) that
  associates controls with frame numbers; it is not Python and does not need
  ``python3-libcamera``. It is a possible future lever, not used here.

Warm-up is a bounded count of captured frames (default 90, one final on top).
It is an initial calibration sample, not proof that AE/AF have converged: the
JPEG is reported as the final captured frame, not as a settled or useful one.
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


PREFIX = "pocketfed-libcamera-session"

REAR = "/base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a"
DEFAULT_STREAM = "role=still,width=1280,height=960,pixelformat=RGB888"
DEFAULT_WARMUP = 90
DEFAULT_TIMEOUT = 60

# Exactly the cam options used, all present in the device's `cam --help`.
CAM_OPTIONS = ("-c", "--stream", "--capture", "--file", "--metadata")

# camera_session.cpp prints one of these per completed request:
#   "<ts> (<fps> fps) <stream> seq: <000123> bytesused: <bytes>"
# Anchoring on "bytesused:" avoids the tab-indented metadata control lines.
SEQUENCE_PATTERN = re.compile(r"seq:\s*(\d+)\s+bytesused:")


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


def descendant_pids(pid):
    found, pending = [], [pid]
    while pending:
        for child in child_pids(pending.pop()):
            if child not in found:
                found.append(child)
                pending.append(child)
    return found


def pid_alive(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return False
    return fields[0] not in {"Z", "X"}


def terminate_process_tree(process, grace=2.0):
    """Kill cam and its helpers without touching the gate.

    cam is started in this helper's own process group (the gate gave the helper
    a new session), so when this helper is the group leader every descendant is
    found by group membership and the gate kills that same group on Volume Down.
    The fallback includes cam itself (only while it is alive) and its
    descendants, so a reaped leader is not reported as a survivor.
    """
    if process is None:
        return []
    if os.getpgrp() == os.getpid():
        def targets():
            return [pid for pid in group_members(os.getpgrp()) if pid != os.getpid()]
    else:
        def targets():
            candidates = [process.pid] + descendant_pids(process.pid)
            return [pid for pid in candidates if pid_alive(pid)]

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


def run_cam(command, log_path, timeout):
    result = {"timed_out": False, "returncode": None, "remaining": []}
    with log_path.open("w") as stream:
        # No start_new_session: cam stays inside the helper's group so the gate's
        # group cancellation reaches it, and terminate_process_tree can find it.
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
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
    return result


def frame_sequences(text):
    """Return (completed-frame count, min sequence, max sequence) from a cam log.

    The count is the number of completed-request lines, never derived from the
    maximum sequence: sequences can start above zero or contain gaps.
    """
    sequences = [int(match.group(1)) for match in SEQUENCE_PATTERN.finditer(text)]
    if not sequences:
        return 0, None, None
    return len(sequences), min(sequences), max(sequences)


def power_gate(power_state, output, timeout=10):
    result = subprocess.run(
        [sys.executable, str(power_state), "--require-released",
         "--timeout", str(timeout)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout + 10, check=False)
    output.write_text(result.stdout)
    if result.returncode:
        raise SessionError(f"camera release gate failed ({output.name})")


def run_command(argv, timeout=30):
    return subprocess.run(argv, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout,
                          check=False)


def convert_to_jpeg(magick, source, target, timeout=30):
    result = run_command([magick, str(source), str(target)], timeout=timeout)
    if result.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SessionError(f"JPEG conversion failed: {result.stdout.strip()}")


def decode_file(magick, path, timeout=30):
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


def build_cam_command(args, total, output_file):
    # No '#' and a fixed .ppm name: file_sink's expansion never runs and
    # PPMWriter truncation leaves only the final frame on disk.
    return [str(args.cam_entry), "-c", args.camera,
            f"--stream={args.stream}", f"--capture={total}",
            "--metadata", f"--file={output_file}"]


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
        "frames_captured": None,
        "sequence_min": None,
        "sequence_max": None,
        "camera_attempted": False,
        "camera_released": None,
        "release_error": None,
        "ppm": None,
        "jpeg": None,
        "geometry": None,
        "metadata_log": str(output / "cam.log"),
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
    try:
        reporter.state("preflight")
        if not os.access(args.cam_entry, os.X_OK):
            raise SessionError(f"cam entry not executable: {args.cam_entry}")
        if not Path(args.power_state).is_file():
            raise SessionError(f"power-state helper missing: {args.power_state}")
        reporter.state("release-gate", "before")
        power_gate(Path(args.power_state), output / "power-before.json")
        total = args.warmup + 1
        frame_file = output / "frame.ppm"
        command = build_cam_command(args, total, frame_file)
        reporter.state("capture", f"warmup-frames={args.warmup} total={total}")
        camera_attempted = True
        report["camera_attempted"] = True
        cam = run_cam(command, output / "cam.log", args.timeout)
        report["cam"] = cam
        if cam["timed_out"] or cam["returncode"] != 0 or cam["remaining"]:
            raise SessionError("cam run failed or did not stop cleanly")
        captured, sequence_min, sequence_max = frame_sequences(
            (output / "cam.log").read_text())
        report["frames_captured"] = captured
        report["sequence_min"] = sequence_min
        report["sequence_max"] = sequence_max
        if captured < total:
            raise SessionError(
                f"cam reported {captured} completed frames, expected {total}")
        if not frame_file.is_file() or frame_file.stat().st_size == 0:
            raise SessionError("no final frame was saved")
        width, height = expected_geometry(args.stream)
        ppm_geometry = identify(args.magick, frame_file)
        if ppm_geometry != f"PPM {width} {height}":
            raise SessionError(f"unexpected final frame geometry: {ppm_geometry}")
        decode_file(args.magick, frame_file)
        report["ppm"] = str(frame_file)
        jpeg = output / "final.jpg"
        convert_to_jpeg(args.magick, frame_file, jpeg)
        decode_file(args.magick, jpeg)
        jpeg_geometry = identify(args.magick, jpeg)
        if not jpeg_geometry.startswith(f"JPEG {width} {height}"):
            raise SessionError(f"unexpected JPEG geometry: {jpeg_geometry}")
        report["jpeg"] = str(jpeg)
        report["geometry"] = jpeg_geometry
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
        # cannot skip the release gate or the result write. The first delivered
        # signal is the one already captured above.
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        cleanup_started = True
        try:
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
        reporter.state("complete",
                       f"{report['jpeg']} frames={report['frames_captured']}")
        return 0
    if report["status"] == "cancelled":
        return 130 if cancel_signum == signal.SIGINT else 143
    return 1


def preflight(args):
    missing = []
    if not Path(args.cam_entry).exists():
        missing.append(str(args.cam_entry))
    if not Path(args.power_state).is_file():
        missing.append(str(args.power_state))
    if shutil.which(args.magick) is None:
        missing.append(args.magick)
    if missing:
        raise SessionError("missing required tools: " + ", ".join(missing))


def build_parser(default_dir):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh private directory for this session's output")
    parser.add_argument("--camera", default=REAR)
    parser.add_argument("--stream", default=DEFAULT_STREAM)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                        help="captured warm-up frames before the final frame "
                             "(default 90; a calibration sample, not proven settling)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="bound for the whole cam run, seconds (default 60)")
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
    if not 1 <= args.warmup <= 2000:
        raise SystemExit("--warmup must be 1..2000")
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
