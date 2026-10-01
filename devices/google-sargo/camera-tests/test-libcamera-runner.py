#!/usr/bin/env python3
"""Exercise the runner's observed failure cases without camera hardware."""

from pathlib import Path
import runpy
import subprocess
import sys
import tempfile


runner = runpy.run_path(str(Path(__file__).with_name("run-libcamera.py")))


def expect_invalid(directory):
    try:
        runner["validate_frames"](directory)
    except (RuntimeError, subprocess.CalledProcessError):
        return
    raise AssertionError("Invalid or missing frames were accepted")


with tempfile.TemporaryDirectory(prefix="sargo-capture-runner-") as temporary:
    directory = Path(temporary)
    # A process exit of zero cannot stand in for saved image files.
    result = runner["run_capture"]([sys.executable, "-c", "pass"],
                                    directory / "empty.log", 1)
    assert result["returncode"] == 0
    expect_invalid(directory)

    valid = b"P6\n1280 960\n255\n" + bytes([128, 128, 128]) * (1280 * 960)
    for i in range(3):
        (directory / f"rear-{i}.ppm").write_bytes(valid)
    assert len(runner["validate_frames"](directory)) == 3
    (directory / "rear-0.ppm").write_bytes(valid[:100])
    expect_invalid(directory)  # Valid header, incomplete pixels.
    (directory / "rear-0.ppm").write_bytes(bytes(1280 * 960))
    expect_invalid(directory)  # Raw bytes with a misleading .ppm extension.
    (directory / "rear-0.ppm").write_bytes(b"P6\n1 1\n255\n\x80\x80\x80")
    expect_invalid(directory)
    print("PASS: full pixel validation accepts three RGB frames and rejects missing, truncated, raw and wrong-size files")

    for mode in ("timeout", "orphan"):
        command = '''import subprocess,sys,signal,time
child = subprocess.Popen([sys.executable, "-c",
    "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"])
print(child.pid, flush=True)
'''
        if mode == "timeout":
            command += '''signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(60)
'''
        log = directory / f"{mode}.log"
        result = runner["run_capture"]([sys.executable, "-c", command], log, 1)
        child_pid = int(log.read_text().splitlines()[0])
        state = Path(f"/proc/{child_pid}/stat")
        assert not state.exists() or state.read_text().rsplit(")", 1)[1].split()[0] in {"Z", "X"}
        assert result["remaining_processes"] == []
        assert result["timed_out"] == (mode == "timeout")
        if mode == "orphan":
            assert result["returncode"] == 0
    print("PASS: timeout and normal-parent-exit cases leave no live child helper, including a child that ignores TERM")

print("Synthetic runner checks only; no camera frames were captured")
