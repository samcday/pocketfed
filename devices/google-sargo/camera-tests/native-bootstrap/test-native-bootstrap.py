#!/usr/bin/env python3
"""Static and argument validation for the Sargo native bootstrap.

Runs only bash parsing and the script's own --check path with simulated
platform inputs. It never invokes dnf, rpmbuild, git, systemctl, a camera or
any device operation.
"""

from pathlib import Path
import re
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name("native-bootstrap.sh")
COMMAND = ["bash", str(SCRIPT)]

FORBIDDEN_TOKENS = (
    "rpm-ostree",
    "systemctl",
    "loginctl",
    "reboot",
    "poweroff",
    "shutdown",
    "usroverlay",
    "suspend",
    "hibernate",
)
DESTRUCTIVE_DNF = re.compile(r"\bdnf\b[^\n]*\b(upgrade|distro-sync|remove|autoremove|module)\b")


def run(*args):
    return subprocess.run(
        [*COMMAND, *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def executable_lines():
    for line in SCRIPT.read_text().splitlines():
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            yield line


def main():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, "bootstrap script is not executable"

    syntax = subprocess.run(["bash", "-n", str(SCRIPT)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert syntax.returncode == 0, f"bash -n failed:\n{syntax.stdout}"

    help_result = run("--help")
    assert help_result.returncode == 0, "--help did not exit 0"
    assert "Safety" in help_result.stdout and "--expect-run-id" in help_result.stdout

    assert run("--definitely-not-a-flag").returncode != 0, "unknown argument accepted"

    with tempfile.TemporaryDirectory(prefix="native-bootstrap-test-") as directory:
        root = Path(directory)
        liveboot = root / "cmdline"
        liveboot.write_text("console=ttyMSM0,115200n8 pocketfed.liveboot=run-abc "
                            "pocketfed.root_mode=usb\n")
        plain = root / "cmdline-plain"
        plain.write_text("console=ttyMSM0,115200n8\n")
        absent_result = root / "no-result.json"

        def check(*extra):
            return run("--check", "--machine-arch", "aarch64", "--result-file",
                       str(absent_result), "--build-root", str(root / "build"), *extra)

        bad_arch = run("--check", "--machine-arch", "x86_64", "--root-fstype",
                       "overlay", "--cmdline-file", str(liveboot),
                       "--result-file", str(absent_result), "--expect-run-id", "run-abc")
        assert bad_arch.returncode != 0 and "aarch64" in bad_arch.stdout

        persistent = check("--root-fstype", "ext4", "--cmdline-file", str(liveboot),
                           "--expect-run-id", "run-abc")
        assert persistent.returncode != 0 and "overlay" in persistent.stdout

        not_liveboot = check("--root-fstype", "overlay", "--cmdline-file", str(plain),
                             "--expect-run-id", "run-abc")
        assert not_liveboot.returncode != 0 and "pocketfed.liveboot" in not_liveboot.stdout

        missing_expect = check("--root-fstype", "overlay", "--cmdline-file", str(liveboot))
        assert missing_expect.returncode != 0 and "--expect-run-id" in missing_expect.stdout

        mismatch = check("--root-fstype", "overlay", "--cmdline-file", str(liveboot),
                         "--expect-run-id", "run-xyz")
        assert mismatch.returncode != 0 and "mismatch" in mismatch.stdout

        valid = check("--root-fstype", "overlay", "--cmdline-file", str(liveboot),
                      "--expect-run-id", "run-abc")
        assert valid.returncode == 0, f"valid check failed:\n{valid.stdout}"
        assert not (root / "build").exists(), "--check created its build root"
        for expected in ("libdng", "libmegapixels", "megapixels", "libcamera",
                         "libcamera-ipa", "libcamera-tools", "v4l-utils"):
            assert expected in valid.stdout, f"plan omits {expected}"

    for line in executable_lines():
        lowered = line.lower()
        for token in FORBIDDEN_TOKENS:
            assert token not in lowered, f"forbidden operation token '{token}' in: {line.strip()}"
        assert not DESTRUCTIVE_DNF.search(lowered), f"destructive dnf verb in: {line.strip()}"

    install_lines = [line for line in executable_lines() if "dnf install" in line]
    assert len(install_lines) >= 2, \
        f"expected bootstrap and local-RPM dnf install invocations, got {install_lines}"

    print("PASS: syntax, arguments, platform/run-identity guards, plan and safety scan")


if __name__ == "__main__":
    main()
