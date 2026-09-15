#!/usr/bin/env python3
"""Static and guard validation for packages/libcamera/build-native.

Runs only bash parsing, argument handling and the helper's pure functions
through bash `source`. It never invokes rpmbuild, dnf, or a device, and it
does not build an RPM.
"""

from pathlib import Path
import hashlib
import json
import os
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
SUBPACKAGES = ("devel", "ipa", "tools", "qcam", "gstreamer", "v4l2")


def run(*args):
    return subprocess.run(["bash", str(HELPER), *args], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def sourced(body, *args):
    return subprocess.run(["bash", "-c", 'source "$1"; shift; ' + body, "bash",
                           str(HELPER), *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def shell_value(name):
    result = subprocess.run(
        ["bash", "-c", f'source "$1"; printf "%s" "${{{name}}}"', "bash", str(HELPER)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert result.returncode == 0, result.stdout
    return result.stdout


def spec_fixture(directory, *, marker=True, requires=len(SUBPACKAGES),
                 extra_package=False):
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
    for name in SUBPACKAGES:
        lines += [f"%package {name}", "Summary: test"]
        if requires > 0:
            lines.append("Requires: %{name}%{?_isa} = %{version}-%{release}")
            requires -= 1
        lines += [f"%description {name}", "test"]
    lines += ["%package -n python3-libcamera", "Summary: test",
              "Requires: %{name}%{?_isa} = %{version}-%{release}",
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
    for flag in ("--build-root", "--iteration", "--srpm", "--clone", "--check"):
        assert flag in help_result.stdout, f"--help omits {flag}"

    assert run("--nonsense").returncode != 0, "unknown argument accepted"
    missing_cases = (
        (("--srpm", "x", "--clone", "y", "--iteration", "1"), "--build-root"),
        (("--build-root", "/var/tmp/x", "--clone", "y", "--iteration", "1"), "--srpm"),
        (("--build-root", "/var/tmp/x", "--srpm", "y", "--iteration", "1"), "--clone"),
        (("--build-root", "/var/tmp/x", "--srpm", "y", "--clone", "z"), "--iteration"),
    )
    for args, message in missing_cases:
        result = run(*args)
        assert result.returncode != 0 and message in result.stdout, \
            f"missing {message} not reported: {result.stdout}"

    base = ["--build-root", "/var/tmp/x", "--srpm", "y", "--clone", "z"]
    for bad in ("0", "abc", "-1", "1x", ""):
        result = run(*base, "--iteration", bad)
        assert result.returncode != 0 and "iteration" in result.stdout, \
            f"iteration '{bad}' accepted: {result.stdout}"

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
    safe = ("/var/tmp/pocketfed-libcamera-native-test",
            "/var/tmp/pocketfed-libcamera-native-test/deeper",
            "/run/pocketfed-libcamera-native-1")
    for path in safe:
        assert sourced('validate_build_root_path "$@"', path).returncode == 0, \
            f"safe build root rejected: {path}"
    unsafe = ("/", "/var/tmp", "/tmp/pocketfed-libcamera", "/run/other",
              "/run/pocketfed-libcamera-native-1/../../etc", "/run",
              str(REPO), str(REPO / "out/liveboot/libcamera"))
    for path in unsafe:
        assert sourced('validate_build_root_path "$@"', path).returncode != 0, \
            f"unsafe build root accepted: {path}"

    link = Path("/var/tmp") / f"pocketfed-libcamera-native-{os.getpid()}-link"
    real = Path("/var/tmp") / f"pocketfed-libcamera-native-{os.getpid()}-real"
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
    assert sourced('verify_spec_properties "$@"',
                   str(spec_fixture(tmp)), ".fc46.native.1").returncode == 0

    no_marker = tmp / "nomarker"
    no_marker.mkdir()
    missing = sourced('verify_spec_properties "$@"',
                      str(spec_fixture(no_marker, marker=False)), ".fc46.native.1")
    assert missing.returncode != 0 and "re-sign" in missing.stdout

    loose = tmp / "loose"
    loose.mkdir()
    unpinned = sourced('verify_spec_properties "$@"',
                       str(spec_fixture(loose, requires=1)), ".fc46.native.1")
    assert unpinned.returncode != 0 and "Requires" in unpinned.stdout

    extra = tmp / "extra"
    extra.mkdir()
    unexpected = sourced('verify_spec_properties "$@"',
                         str(spec_fixture(extra, extra_package=True)), ".fc46.native.1")
    assert unexpected.returncode != 0 and "subpackage" in unexpected.stdout


def test_spec_glob_correction(tmp):
    original = shell_value("IPA_RESIGN_GLOB")
    corrected = shell_value("IPA_RESIGN_GLOB_FIXED")
    assert original and corrected and original != corrected

    good = Path(tmp) / "good.spec"
    good.write_text("%define __spec_install_post \\\n"
                    "    .../ipa-sign-install.sh key " + original + " \\\n")
    result = sourced('correct_fedora_spec "$1" >/dev/null; '
                     'printf "%s %s" "$spec_original_sha256" "$spec_packaged_sha256"',
                     str(good))
    assert result.returncode == 0, result.stdout
    text = good.read_text()
    assert corrected in text and original not in text, text
    recorded = result.stdout.split()
    assert len(recorded) == 2 and recorded[0] != recorded[1]
    assert all(len(value) == 64 for value in recorded)

    absent = Path(tmp) / "absent.spec"
    absent.write_text("%define __spec_install_post \\\n    /bin/true\n")
    before = absent.read_text()
    failed = sourced('correct_fedora_spec "$@"', str(absent))
    assert failed.returncode != 0 and "expected single occurrence" in failed.stdout
    assert absent.read_text() == before

    unexpected = Path(tmp) / "unexpected.spec"
    unexpected.write_text(original.replace("ipa_*.so", "other/ipa_*.so") + "\n")
    assert sourced('correct_fedora_spec "$@"', str(unexpected)).returncode != 0


def test_manifest(tmp):
    manifest = Path(tmp) / "manifest.json"
    body = ('build_root=/tmp/x; iteration=3; dist=.fc46.native.3; '
            'release=4.fc46.native.3; srpm=/tmp/libcamera.src.rpm; '
            'srpm_sha256=aaaa; source_archive_sha256=bbbb; '
            'spec_original_sha256=1111; spec_packaged_sha256=2222; '
            'fedora_patches="0001-x.patch cccc"; task_patches=""; '
            'rpms_records="/x/libcamera.rpm dddd"; write_manifest "$1"')
    result = sourced(body, str(manifest))
    assert result.returncode == 0, result.stdout
    data = json.loads(manifest.read_text())
    assert data["iteration"] == 3
    assert data["dist"] == ".fc46.native.3" and data["release"] == "4.fc46.native.3"
    assert data["srpm"] == {"name": "libcamera.src.rpm", "sha256": "aaaa"}
    assert data["source_archive"]["expected_sha256"] == PINNED["libcamera-v0.7.2.tar.bz2"]
    assert data["source_archive"]["regenerated_sha256"] == "bbbb"
    assert data["fedora_patches"] == [{"name": "0001-x.patch", "sha256": "cccc"}]
    assert data["task_patches"] == []
    assert data["fedora_spec"]["original_sha256"] == "1111"
    assert data["fedora_spec"]["packaged_sha256"] == "2222"
    assert data["fedora_spec"]["changes"][0]["to"] == shell_value("IPA_RESIGN_GLOB_FIXED")
    assert data["rpms"] == [{"name": "/x/libcamera.rpm", "sha256": "dddd"}]
    assert data["toolchain"]["arch"]


def main():
    assert HELPER.is_file(), f"missing {HELPER}"
    test_arguments_and_pins()
    with tempfile.TemporaryDirectory(prefix="libcamera-build-native-test-") as tmp:
        root = Path(tmp)
        test_hash_guard(root)
        test_build_root_guard(root)
        test_clone_guard(root)
        test_spec_guard(root)
        test_spec_glob_correction(root)
        test_manifest(root)
    print("PASS: syntax, arguments, pins, hash/build-root/clone/spec guards, "
          "spec glob correction, manifest")


if __name__ == "__main__":
    main()
