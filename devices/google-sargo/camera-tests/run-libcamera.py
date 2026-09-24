#!/usr/bin/env python3
"""Capture three rear RGB frames with bounded waits and verify saved pixels.

Run as root on sam-sargo with cam, libcamera-ipa, ImageMagick and the adjacent
cam-system-heap / power-state.py helpers installed. Scene output stays private.
This checks transport and release, not photograph quality or UI acceptance.
"""

import argparse
import errno
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


REAR = "/base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a"


def group_members(group):
    """Return live members of the private process group, excluding zombies."""
    members = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ESRCH):
                continue
            raise
        if int(fields[2]) == group and fields[0] not in {"Z", "X"}:
            members.append(int(path.parent.name))
    return members


def signal_group(group, signum):
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        pass


def run_capture(command, log, timeout):
    """Give cam SIGINT to stop normally, then clean up its private group."""
    result = {"timed_out": False}
    with log.open("w") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=stream,
                                   start_new_session=True)
        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            # A failed cam can leave soft_ipa_proxy children after its own exit.
            # Never use a process-name-wide kill: this group belongs to this run.
            for signum in (signal.SIGTERM, signal.SIGKILL):
                if not group_members(process.pid):
                    break
                signal_group(process.pid, signum)
                deadline = time.monotonic() + 1
                while group_members(process.pid) and time.monotonic() < deadline:
                    time.sleep(.05)
            result["remaining_processes"] = group_members(process.pid)
            try:
                result["returncode"] = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                result["returncode"] = None
    return result


def validate_frames(output):
    frames = sorted(output.glob("rear-*.ppm"))
    if len(frames) != 3:
        raise RuntimeError(f"Expected three saved PPM frames, found {len(frames)}")
    results = []
    for frame in frames:
        # Read all pixels, not just the PPM header or cam's successful exit code.
        subprocess.run(["magick", "-regard-warnings", str(frame), "null:"],
                       check=True, capture_output=True, timeout=20)
        geometry = subprocess.check_output(
            ["magick", "identify", "-format", "%m %w %h", str(frame)],
            text=True, timeout=10).strip()
        if geometry != "PPM 1280 960":
            raise RuntimeError(f"Unexpected saved frame format: {geometry}")
        results.append({"name": frame.name, "bytes": frame.stat().st_size,
                        "format": "PPM", "width": 1280, "height": 960})
    return results


def power_gate(helper, output):
    with output.open("w") as log:
        result = subprocess.run([sys.executable, str(helper), "--require-released",
                                 "--timeout", "10"], stdout=log, stderr=subprocess.STDOUT,
                                timeout=15)
    if result.returncode:
        raise RuntimeError(f"Camera release gate failed; inspect {output.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root for the private DMA-heap namespace and release gate")
    if not 1 <= args.timeout <= 60:
        parser.error("timeout must be 1..60 seconds")
    helpers = Path(__file__).resolve().parent
    missing = [c for c in ("cam", "magick", "rpm", "unshare", "mount", "mknod")
               if shutil.which(c) is None]
    if missing or not os.access(helpers / "cam-system-heap", os.X_OK) or not (helpers / "power-state.py").is_file():
        parser.error("Required commands or adjacent helpers are missing: " + ", ".join(missing))
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {"status": "failed", "camera": REAR, "frames": [], "kernel": os.uname().release,
              "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    capture_started = False
    try:
        report["packages"] = subprocess.check_output(
            ["rpm", "-q", "libcamera", "libcamera-tools", "libcamera-ipa"], text=True, timeout=10)
        power_gate(helpers / "power-state.py", output / "power-before.json")
        capture_started = True
        report["capture"] = run_capture([
            str(helpers / "cam-system-heap"), "-c", REAR,
            "--stream", "role=still,width=1280,height=960,pixelformat=RGB888",
            "--capture=3", "--file=" + str(output / "rear-#.ppm")],
            output / "cam.log", args.timeout)
        capture = report["capture"]
        if capture["timed_out"] or capture["returncode"] != 0 or capture["remaining_processes"]:
            raise RuntimeError("Capture failed or its process group did not stop")
        report["frames"] = validate_frames(output)
        report["status"] = "passed"
    except Exception as error:
        report["error"] = str(error)
    finally:
        if capture_started:
            try:
                power_gate(helpers / "power-state.py", output / "power-after.json")
                report["camera_released"] = True
            except Exception as error:
                report.update(status="failed", camera_released=False, release_error=str(error))
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
