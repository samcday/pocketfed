#!/usr/bin/python3
"""One temporary read-only RPMB listener trial; preserve credentials/history.

Run on the designated installed sam-sargo after copying the reviewed binary.
No provisioning, credential reads, RPMB writes or automated recovery retries.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess


def run(*args):
    return subprocess.run(args, check=True, text=True)


def inactive(unit):
    result = subprocess.check_output(
        ["systemctl", "show", "-p", "MainPID", "--value", unit], text=True
    ).strip()
    assert result == "0", unit


def main():
    assert os.geteuid() == 0 and os.uname().nodename == "sam-sargo"
    assert os.uname().release == "7.1.2-0.pocketfed.sdm670.11.fc46.aarch64"
    state = Path("/var/lib/pocketfed-fpc-auth")
    assert {p.name for p in state.iterdir()} == {
        ".lock", "uid-1000.intent", "uid-1000.first-recovery-attempt"
    }
    for name, size in (("uid-1000.intent", 160), ("uid-1000.first-recovery-attempt", 132)):
        s = (state / name).lstat()
        assert stat.S_ISREG(s.st_mode) and stat.S_IMODE(s.st_mode) == 0o600
        assert s.st_uid == s.st_gid == 0 and s.st_size == size and s.st_nlink == 1
    for unit in ("pocketfed-fpc-auth.service", "pocketfed-fpc-provision@1000.service",
                 "pocketfed-fpc-recover-first.service", "fprintd.service"):
        inactive(unit)
    assert os.readlink("/run/systemd/system/fprintd.service") == "/dev/null"
    for unit in ("pocketfed-fpc-auth.socket", "phosh-fingerprint-auth.socket"):
        assert os.readlink("/etc/systemd/system/" + unit) == "/dev/null"
    trial = Path("/run/sargo-fingerprint-trial")
    s = trial.stat()
    assert s.st_uid == s.st_gid == 0 and stat.S_IMODE(s.st_mode) == 0o700
    binary = trial / "rpmb-supplicant-ro"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == (
        "9a5208af3d26b7575b7db5a89025419f55941efe8b0385a99b7df5f1017e186d"
    )
    override = Path("/run/systemd/system/qsee-supplicant.service.d/99-fingerprint-first-trial.conf")
    original = override.read_text()
    assert original == (
        "[Service]\nRestart=no\nTimeoutStartSec=45\nTimeoutStopSec=infinity\n"
        "ExecStart=\nExecStart=/usr/bin/python3 /run/sargo-fingerprint-trial/listener-single-attempt.py\n"
        "NotifyAccess=all\n"
    )
    lock = os.open("/var/lib/fprint/fpc-qsee/device.lock", os.O_RDWR | os.O_NOFOLLOW)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        # Runtime receipt only; this is not another native credential recovery.
        with (trial / "rpmb-ro-start-attempt").open("x") as receipt:
            receipt.write("Read-only RPMB daemon activation, no credential recovery.\n")
            receipt.flush()
            os.fsync(receipt.fileno())
        with (trial / "qsee-before-rpmb-ro.conf").open("x") as backup:
            backup.write(original)
        binary.chmod(0o700)
        run("chcon", "--reference=/usr/bin/qsee-supplicant", str(binary))
        run("systemctl", "stop", "qsee-app-loader@fpctzappfingerprint.service",
            "qsee-shared-loader@cmnlib64.service", "qsee-supplicant.service")
        override.write_text(
            "[Service]\nRestart=no\nTimeoutStartSec=45\nTimeoutStopSec=infinity\n"
            "ExecStart=\nExecStart=/run/sargo-fingerprint-trial/rpmb-supplicant-ro --serve-read-only\n"
            "NotifyAccess=main\n"
        )
        run("systemctl", "daemon-reload")
        run("systemctl", "start", "qsee-supplicant.service")
        run("systemctl", "start", "qsee-shared-loader@cmnlib64.service")
        run("systemctl", "start", "qsee-app-loader@fpctzappfingerprint.service")
        print("read_only_rpmb_activation=ready", flush=True)
    finally:
        os.close(lock)


if __name__ == "__main__":
    main()
