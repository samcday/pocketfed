#!/usr/bin/env python3
"""Static and argument validation for the Sargo native bootstrap.

Runs only bash parsing, the script's --check guards with simulated platform
inputs, and the script's pure RPM-selection functions via bash `source`. It
never invokes dnf, rpmbuild, git, systemctl, a camera or any device action.
"""

from pathlib import Path
import os
import re
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name("native-bootstrap.sh")
REPO = SCRIPT.resolve().parents[4]
COMMAND = ["bash", str(SCRIPT)]
FIXTURE_VERSION = ".fc46.native"
BUILD_ROOT = Path("/var/tmp") / f"native-bootstrap-test-{os.getpid()}-build"

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

PKGCONFIG_TO_PACKAGE = {
    "pkgconfig(libtiff-4)": "libtiff-devel",
    "pkgconfig(libconfig)": "libconfig-devel",
    "pkgconfig(gtk4)": "gtk4-devel",
    "pkgconfig(libfeedback-0.0)": "feedbackd-devel",
    "pkgconfig(zbar)": "zbar-devel",
    "pkgconfig(epoxy)": "libepoxy-devel",
    "pkgconfig(libjpeg)": "libjpeg-turbo-devel",
    "pkgconfig(libpulse-simple)": "pulseaudio-libs-devel",
    "pkgconfig(wayland-client)": "wayland-devel",
    "pkgconfig(x11)": "libX11-devel",
    "pkgconfig(xrandr)": "libXrandr-devel",
    "pkgconfig(scdoc)": "scdoc",
    "pkgconfig(libmegapixels)": None,
    "pkgconfig(libdng)": None,
}


def run(*args):
    return subprocess.run([*COMMAND, *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def sourced(body, *args):
    return subprocess.run(["bash", "-c", 'source "$1"; shift; ' + body, "bash",
                           str(SCRIPT), *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def check_sim(root, cmdline, *extra):
    return run("--check", "--machine-arch", "aarch64", "--root-fstype", "overlay",
               "--cmdline-file", str(cmdline), "--result-file", str(root / "absent.json"),
               "--build-root", str(BUILD_ROOT), *extra)


def executable_lines():
    for line in SCRIPT.read_text().splitlines():
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            yield line


def test_arguments_and_safety():
    assert SCRIPT.stat().st_mode & 0o111, "bootstrap script is not executable"
    syntax = subprocess.run(["bash", "-n", str(SCRIPT)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert syntax.returncode == 0, f"bash -n failed:\n{syntax.stdout}"
    help_result = run("--help")
    assert help_result.returncode == 0 and "Safety" in help_result.stdout
    assert run("--definitely-not-a-flag").returncode != 0

    for line in executable_lines():
        lowered = line.lower()
        for token in FORBIDDEN_TOKENS:
            assert token not in lowered, f"forbidden operation token '{token}' in: {line.strip()}"
        assert not DESTRUCTIVE_DNF.search(lowered), f"destructive dnf verb in: {line.strip()}"
    install_lines = [line for line in executable_lines() if "dnf install" in line]
    assert len(install_lines) >= 2, f"expected dnf install invocations, got {install_lines}"


def test_overrides_are_check_only():
    for override in (["--machine-arch", "aarch64"], ["--cmdline-file", "/dev/null"],
                     ["--root-fstype", "overlay"], ["--result-file", "/dev/null"]):
        result = run(*override)
        assert result.returncode != 0 and "only allowed with --check" in result.stdout, \
            f"{override} was accepted for install: {result.stdout}"


def test_guards(root, liveboot, plain):
    assert run("--check", "--machine-arch", "x86_64", "--root-fstype", "overlay",
               "--cmdline-file", str(liveboot), "--result-file", str(root / "absent.json"),
               "--expect-run-id", "run-abc").returncode != 0
    assert check_sim(root, liveboot, "--root-fstype", "ext4",
                     "--expect-run-id", "run-abc").returncode != 0
    assert check_sim(root, plain, "--expect-run-id", "run-abc").returncode != 0
    assert check_sim(root, liveboot).returncode != 0
    assert check_sim(root, liveboot, "--expect-run-id", "run-xyz").returncode != 0
    valid = check_sim(root, liveboot, "--expect-run-id", "run-abc")
    assert valid.returncode == 0, f"valid check failed:\n{valid.stdout}"
    assert not BUILD_ROOT.exists(), "--check created its build root"
    for expected in ("libdng", "libmegapixels", "megapixels", "libcamera",
                     "libcamera-ipa", "libcamera-tools", "v4l-utils"):
        assert expected in valid.stdout, f"plan omits {expected}"


def test_build_root_paths(root, liveboot):
    bad = ("/etc/pocketfed", "/var/tmp", "/var/tmp/../etc/x", "relative/path", "/")
    for path in bad:
        result = check_sim(root, liveboot, "--expect-run-id", "run-abc", "--build-root", path)
        assert result.returncode != 0, f"unsafe build root accepted: {path}"
        assert "build root" in result.stdout, f"missing build-root error for {path}"

    link = Path("/var/tmp") / f"native-bootstrap-test-{os.getpid()}-link"
    target = Path("/var/tmp") / f"native-bootstrap-test-{os.getpid()}-real"
    if link.exists() or link.is_symlink():
        link.unlink()
    try:
        target.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        result = check_sim(root, liveboot, "--expect-run-id", "run-abc", "--build-root", str(link))
        assert result.returncode != 0 and "symlink" in result.stdout, \
            f"symlink build root accepted: {result.stdout}"
    finally:
        if link.is_symlink():
            link.unlink()
        if target.exists():
            target.rmdir()


def test_build_user_and_owner(root, liveboot):
    assert "uid 0" in sourced("build_user=root; require_build_user").stdout

    owned = Path("/var/tmp") / f"native-bootstrap-test-{os.getpid()}-owned"
    owned.mkdir(parents=True, exist_ok=True)
    try:
        mine = sourced("validate_build_root_owner \"$1\" \"$2\"", str(owned), str(os.getuid()))
        assert mine.returncode == 0, f"owner check rejected the build user: {mine.stdout}"
        mismatch = check_sim(root, liveboot, "--expect-run-id", "run-abc",
                             "--build-user", "root", "--build-root", str(owned))
        assert mismatch.returncode != 0 and "owned by uid" in mismatch.stdout, \
            f"unexpected owner accepted: {mismatch.stdout}"
    finally:
        owned.rmdir()


def test_rpm_selection(root):
    spec = REPO / "packages" / "libdng" / "libdng.spec"
    rpm_dir = root / "rpmbuild" / "RPMS" / "aarch64"
    rpm_dir.mkdir(parents=True)
    expected = sourced("resolve_expected_rpms \"$@\"", str(spec), str(rpm_dir),
                       FIXTURE_VERSION, "aarch64")
    assert expected.returncode == 0, expected.stdout
    names = expected.stdout.split()
    assert len(names) == 3 and all(f"0.2.2-1{FIXTURE_VERSION}" in n for n in names), names
    assert not any("debug" in n for n in names), names

    for name in names:
        (rpm_dir / Path(name).name).touch()
    (rpm_dir / f"libdng-0.1.0-1{FIXTURE_VERSION}.aarch64.rpm").touch()
    (rpm_dir / f"libdng-debuginfo-0.2.2-1{FIXTURE_VERSION}.aarch64.rpm").touch()

    collected = sourced("collect_rpms \"$@\"", str(spec), str(rpm_dir),
                        FIXTURE_VERSION, "aarch64")
    assert collected.returncode == 0, collected.stdout
    selected = collected.stdout.split()
    assert selected == names, f"stale/debug RPM selected: {selected}"

    Path(names[0]).unlink()
    missing = sourced("collect_rpms \"$@\"", str(spec), str(rpm_dir),
                      FIXTURE_VERSION, "aarch64")
    assert missing.returncode != 0 and "missing" in missing.stdout, missing.stdout


def test_dependency_coverage():
    text = SCRIPT.read_text()
    declared = set(re.search(r"readonly BUILD_PACKAGES=\((.*?)\)", text, re.S).group(1).split())
    for package in ("libdng", "libmegapixels", "megapixels"):
        spec = (REPO / "packages" / package / f"{package}.spec").read_text()
        for requirement in re.findall(r"^BuildRequires:\s*(.+)$", spec, re.M):
            token = requirement.split()[0]
            if token in PKGCONFIG_TO_PACKAGE:
                mapped = PKGCONFIG_TO_PACKAGE[token]
                if mapped is not None:
                    assert mapped in declared, f"{package} needs {mapped}, not declared"
            else:
                assert token in declared, f"{package} needs {token}, not declared"


def main():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    test_arguments_and_safety()
    test_overrides_are_check_only()
    with tempfile.TemporaryDirectory(prefix="native-bootstrap-test-") as directory:
        root = Path(directory)
        liveboot = root / "cmdline"
        liveboot.write_text("console=ttyMSM0 pocketfed.liveboot=run-abc pocketfed.root_mode=usb\n")
        plain = root / "cmdline-plain"
        plain.write_text("console=ttyMSM0\n")
        test_guards(root, liveboot, plain)
        test_build_root_paths(root, liveboot)
        test_build_user_and_owner(root, liveboot)
        test_rpm_selection(root)
        test_dependency_coverage()
    print("PASS: syntax, arguments, path/override/user guards, RPM selection, deps, safety scan")


if __name__ == "__main__":
    main()
