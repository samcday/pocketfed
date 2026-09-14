#!/usr/bin/env python3
"""Static and guard validation for packages/libcamera/build-native.

Runs only bash parsing, argument handling and the helper's pure guard
functions through bash `source`. It never invokes rpmbuild, dnf, git against a
real clone, or any device action, and it does not build an RPM.
"""

from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
HELPER = PACKAGE / "build-native"
SOURCES = PACKAGE / "sources.sha256"
REPO = PACKAGE.parents[1]

PINNED = {
    "libcamera-0.7.2-4.fc46.src.rpm": "22708eba16c1f17a918e602da7e2d5372dabb7024ee71f9a2e0365a1f99f01fc",
    "libcamera-v0.7.2.tar.bz2": "6f35dd479dd634a1ec50852fa9716c9da81a6c07af93bbf2990f7bbd829f0dfd",
}
SUBPACKAGES = (
    "libcamera",
    "libcamera-devel",
    "libcamera-gstreamer",
    "libcamera-ipa",
    "libcamera-qcam",
    "libcamera-tools",
    "libcamera-v4l2",
    "python3-libcamera",
)


def run(*args):
    return subprocess.run(["bash", str(HELPER), *args], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def sourced(body, *args):
    return subprocess.run(["bash", "-c", 'source "$1"; shift; ' + body, "bash",
                           str(HELPER), *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def spec_fixture(directory, *, marker=True, extra_package=False):
    lines = [
        "Name: libcamera",
        "Version: 0.7.2",
        "Release: 4%{?dist}",
        "Summary: test",
        "License: LGPL-2.1-or-later",
    ]
    if marker:
        lines.append("%global ipa_signer ipa-sign-install.sh")
    lines += ["%description", "test"]
    for name in ("devel", "ipa", "tools", "qcam", "gstreamer", "v4l2"):
        lines += [f"%package {name}", "Summary: test", f"%description {name}", "test"]
    lines += ["%package -n python3-libcamera", "Summary: test",
              "%description -n python3-libcamera", "test"]
    if extra_package:
        lines += ["%package extra", "Summary: test", "%description extra", "test"]
    path = Path(directory) / "libcamera.spec"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_arguments_and_pins():
    assert HELPER.stat().st_mode & 0o111, "build-native is not executable"
    syntax = subprocess.run(["bash", "-n", str(HELPER)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert syntax.returncode == 0, f"bash -n failed:\n{syntax.stdout}"

    help_result = run("--help")
    assert help_result.returncode == 0, "--help did not exit 0"
    for flag in ("--build-root", "--srpm", "--clone", "--check"):
        assert flag in help_result.stdout, f"--help omits {flag}"

    assert run("--nonsense").returncode != 0, "unknown argument accepted"
    for args, message in ((("--srpm", "x", "--clone", "y"), "--build-root"),
                          (("--build-root", "/var/tmp/x", "--clone", "y"), "--srpm"),
                          (("--build-root", "/var/tmp/x", "--srpm", "y"), "--clone")):
        result = run(*args)
        assert result.returncode != 0 and message in result.stdout, \
            f"missing {message} not reported: {result.stdout}"

    pins = dict(reversed(line.split()) for line in SOURCES.read_text().splitlines() if line)
    assert pins == PINNED, f"pin mismatch: {pins}"


def test_hash_guard(tmp):
    target = Path(tmp) / "artifact"
    target.write_text("libcamera\n")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert sourced('verify_file_hash "$@"', str(target), digest).returncode == 0
    assert sourced('verify_file_hash "$@"', str(target), "0" * 64).returncode != 0
    assert sourced('verify_file_hash "$@"', str(target), "").returncode != 0
    assert sourced('verify_file_hash "$@"', str(Path(tmp) / "absent"), digest).returncode != 0


def test_build_root_guard(tmp):
    safe = "/var/tmp/pocketfed-libcamera-native-test"
    assert sourced('validate_build_root_path "$@"', safe).returncode == 0
    for unsafe in ("/", "/var/tmp", "/var/tmp/../etc/x", "/tmp/pocketfed-libcamera",
                   str(REPO), str(REPO / "out/liveboot/libcamera"),
                   os.path.join(tmp, "relative-ok-but-not-var-tmp")):
        result = sourced('validate_build_root_path "$@"', unsafe)
        assert result.returncode != 0, f"unsafe build root accepted: {unsafe}"

    link = Path("/var/tmp") / f"libcamera-native-test-{os.getpid()}-link"
    real = Path("/var/tmp") / f"libcamera-native-test-{os.getpid()}-real"
    if link.is_symlink():
        link.unlink()
    try:
        real.mkdir(exist_ok=True)
        link.symlink_to(real)
        assert sourced('validate_build_root_path "$@"', str(link)).returncode != 0, \
            "symlink build root accepted"
    finally:
        if link.is_symlink():
            link.unlink()
        if real.exists():
            real.rmdir()


def test_clone_guard(tmp):
    clone = Path(tmp) / "clone"
    clone.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    def git(*args):
        return subprocess.run(["git", "-C", str(clone), *args], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    git("init", "-q")
    (clone / "file").write_text("x\n")
    git("add", "file")
    git("commit", "-q", "-m", "init")
    git("tag", "v0.7.2")
    commit = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], text=True,
                            stdout=subprocess.PIPE, check=True).stdout.strip()

    assert sourced('verify_clone "$@"', str(clone), commit, "v0.7.2").returncode == 0
    assert sourced('verify_clone "$@"', str(clone), "0" * 40, "v0.7.2").returncode != 0
    git("tag", "-d", "v0.7.2")
    assert sourced('verify_clone "$@"', str(clone), commit, "v0.7.2").returncode != 0
    git("tag", "v0.7.2")
    (clone / "dirty").write_text("y\n")
    assert sourced('verify_clone "$@"', str(clone), commit, "v0.7.2").returncode != 0


def test_spec_guard(tmp):
    assert sourced('verify_spec_properties "$@"', str(spec_fixture(tmp))).returncode == 0
    no_marker = tmp / "nomarker"
    no_marker.mkdir()
    missing = sourced('verify_spec_properties "$@"',
                      str(spec_fixture(no_marker, marker=False)))
    assert missing.returncode != 0 and "re-sign" in missing.stdout
    extra = tmp / "extra"
    extra.mkdir()
    unexpected = sourced('verify_spec_properties "$@"',
                         str(spec_fixture(extra, extra_package=True)))
    assert unexpected.returncode != 0 and "subpackage" in unexpected.stdout


def main():
    assert HELPER.is_file(), f"missing {HELPER}"
    test_arguments_and_pins()
    with tempfile.TemporaryDirectory(prefix="libcamera-build-native-test-") as tmp:
        root = Path(tmp)
        test_hash_guard(root)
        test_build_root_guard(root)
        test_clone_guard(root)
        test_spec_guard(root)
    print("PASS: syntax, arguments, pins, hash/build-root/clone/spec guards")


if __name__ == "__main__":
    main()
