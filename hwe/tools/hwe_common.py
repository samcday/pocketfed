#!/usr/bin/env python3
"""Shared helpers for the hwe bundle tools, independent of tools/liveboot.

These are copies of exactly the helpers the hwe tools use, taken from commit
47ae272d (before tools/liveboot was removed from the repository):

  tools/liveboot/build-kernel.py:
    BuildError, MAKE_VARIABLES, MODULE_SUFFIXES, sha256, write_json, relative,
    regular, safe_child, inventory, Commands, build_environment, module_key,
    verify_kernel, verify_modules
  tools/liveboot/prepare-fixture.py:
    FixtureError, canonical_kernel
  tools/liveboot/run.py:
    early_modules

Names and behaviour are preserved. `early_modules` is the one adaptation: it
takes a config path directly instead of the old (recipe, repo) pair, because the
hwe tools no longer live inside the liveboot tree.
"""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import subprocess
import time


class BuildError(Exception):
    pass


class FixtureError(Exception):
    pass


MAKE_VARIABLES = {
    "CC", "LD", "AR", "NM", "OBJCOPY", "OBJDUMP", "STRIP", "HOSTCC", "HOSTCXX",
    "LLVM", "LLVM_IAS", "LOCALVERSION", "KCFLAGS", "KAFLAGS", "KCPPFLAGS", "W",
    "KBUILD_BUILD_USER", "KBUILD_BUILD_HOST", "KBUILD_BUILD_TIMESTAMP", "KBUILD_BUILD_VERSION",
}
MODULE_SUFFIXES = (".ko", ".ko.gz", ".ko.xz", ".ko.zst")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def relative(value: str) -> Path:
    if not value or "\\" in value or "\0" in value or any(x in ("", ".", "..") for x in value.split("/")):
        raise BuildError(f"expected a normalized relative path: {value!r}")
    return Path(value)


def regular(path: Path, *, empty: bool = False) -> None:
    if path.is_symlink() or not path.is_file() or (not empty and not path.stat().st_size):
        raise BuildError(f"missing, empty, or non-regular file: {path}")


def safe_child(root: Path, value: str) -> Path:
    child = root
    for part in relative(value).parts:
        child /= part
        if child.is_symlink():
            raise BuildError(f"unexpected symlink: {child}")
    return child


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise BuildError(f"unexpected symlink or special file in bundle: {path}")
        result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def build_environment() -> dict[str, str]:
    env = dict(os.environ)
    # An unrelated shell's Kbuild overrides must not redirect this installation.
    for key in list(env):
        if key.startswith(("KBUILD_", "KCONFIG_", "CONFIG_", "INSTALL_MOD_")) or key in (
                *MAKE_VARIABLES, "ARCH", "CROSS_COMPILE", "MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS",
                "MAKEFILES", "INSTALL_PATH", "MODLIB", "M", "O", "DEPMOD"):
            env.pop(key)
    env["KCONFIG_NOSILENTUPDATE"] = "1"
    return env


class Commands:
    def __init__(self, log: Path, env: dict[str, str]):
        self.log, self.env, self.records = log, env, []

    def run(self, argv: list[str], *, stdout: bool = False) -> str:
        record = {"argv": argv, "started_at": datetime.now(timezone.utc).isoformat()}
        start = time.monotonic()
        with self.log.open("ab") as log:
            log.write(("\n$ " + shlex.join(argv) + "\n").encode())
            log.flush()
            result = subprocess.run(argv, env=self.env, stdout=subprocess.PIPE if stdout else log, stderr=log)
            if stdout:
                log.write(result.stdout)
        record.update(returncode=result.returncode, seconds=round(time.monotonic() - start, 6))
        self.records.append(record)
        if result.returncode:
            raise BuildError(f"command failed ({result.returncode}); see {self.log}: {shlex.join(argv)}")
        return result.stdout.decode().strip() if stdout else ""


def verify_kernel(build: Path, dtb: str, release: str) -> dict[str, Path]:
    if not re.fullmatch(r"[A-Za-z0-9_+.-]+", release) or release in (".", ".."):
        raise BuildError(f"invalid kernel release: {release!r}")
    paths = {"image": safe_child(build, "arch/arm64/boot/Image.gz"),
             "dtb": safe_child(build, "arch/arm64/boot/dts/" + dtb),
             "config": safe_child(build, ".config"),
             "system_map": safe_child(build, "System.map"),
             "modules_order": safe_child(build, "modules.order"),
             "utsrelease": safe_child(build, "include/generated/utsrelease.h")}
    for key, path in paths.items():
        regular(path, empty=key == "modules_order")
    if f'#define UTS_RELEASE "{release}"' not in paths["utsrelease"].read_text().splitlines():
        raise BuildError("generated UTS_RELEASE does not match kernelrelease")
    if "CONFIG_ARM64=y" not in paths["config"].read_text().splitlines():
        raise BuildError("selected configuration is not ARM64")
    try:
        image = gzip.decompress(paths["image"].read_bytes())
    except (OSError, EOFError) as error:
        raise BuildError("Image.gz is not a complete gzip stream") from error
    if len(image) < 64 or image[56:60] != b"ARM\x64":
        raise BuildError("Image.gz does not contain an arm64 Image")
    size = struct.unpack_from("<Q", image, 16)[0]
    if not size or len(image) > size:
        raise BuildError("arm64 Image has an invalid declared image size")
    if ("Linux version " + release + " (").encode() not in image:
        raise BuildError("Image.gz does not contain the selected kernel release banner")
    data = paths["dtb"].read_bytes()
    if len(data) < 40 or struct.unpack_from(">I", data)[0] != 0xD00DFEED or struct.unpack_from(">I", data, 4)[0] != len(data):
        raise BuildError("selected DTB is not a complete flattened device tree")
    return paths


def module_key(name: str) -> str:
    for suffix in MODULE_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    raise BuildError(f"unexpected module filename: {name}")


def verify_modules(install: Path, release: str, order: Path, commands: Commands, modinfo: str) -> dict:
    base = install / "lib/modules"
    if not base.is_dir() or sorted(p.name for p in base.iterdir()) != [release]:
        raise BuildError("modules_install must contain exactly the selected release")
    root = base / release
    for name in ("build", "source"):
        path = root / name
        if path.is_symlink():
            path.unlink()
    files = inventory(install)
    for name in ("modules.dep", "modules.dep.bin", "modules.builtin", "modules.alias", "modules.symbols"):
        if f"lib/modules/{release}/{name}" not in files:
            raise BuildError(f"installed modules lack depmod metadata: {name}")
    expected = set()
    for line in order.read_text().splitlines():
        relative(line)
        if not line.endswith((".o", ".ko")):
            raise BuildError(f"unexpected entry in modules.order: {line}")
        expected.add("kernel/" + (line[:-2] if line.endswith(".o") else line[:-3]))
    modules = [p for p in sorted(root.rglob("*")) if p.is_file() and p.name.endswith(MODULE_SUFFIXES)]
    actual = {module_key(p.relative_to(root).as_posix()) for p in modules}
    if actual != expected or len(modules) != len(actual):
        raise BuildError(f"installed modules differ from build modules.order (missing={sorted(expected-actual)[:5]}, extra={sorted(actual-expected)[:5]})")
    dependency_entries = set()
    for line in (root / "modules.dep").read_text().splitlines():
        name, separator, dependencies = line.partition(":")
        if not separator or name in dependency_entries:
            raise BuildError("modules.dep contains malformed or duplicate entries")
        dependency_entries.add(name)
        for dependency in [name, *dependencies.split()]:
            regular(safe_child(root, dependency))
    if dependency_entries != {p.relative_to(root).as_posix() for p in modules}:
        raise BuildError("modules.dep does not describe every installed module exactly once")
    for offset in range(0, len(modules), 128):
        batch = modules[offset:offset + 128]
        versions = commands.run([modinfo, "-F", "vermagic", *map(str, batch)], stdout=True).splitlines()
        if len(versions) != len(batch) or any(not v.split() or v.split()[0] != release for v in versions):
            raise BuildError("installed module vermagic does not match the selected release")
    return files


def canonical_kernel(data: bytes) -> bytes:
    """Decode Linux EFI zboot, gzip, zstd, or a raw arm64 Image.

    zboot field offsets are defined in Linux's
    drivers/firmware/efi/libstub/zboot-header.S and mirrored by abl-exorcist.
    """
    compression = None
    if len(data) >= 64 and data[:2] == b"MZ" and data[4:8] == b"zimg":
        offset, size = struct.unpack_from("<II", data, 8)
        if offset < 64 or size == 0 or offset + size > len(data):
            raise FixtureError("Linux EFI zboot payload is out of bounds")
        compression = data[24:56].split(b"\0", 1)[0]
        data = data[offset:offset + size]
        if compression not in (b"gzip", b"zstd"):
            raise FixtureError(f"unsupported Linux EFI zboot compression: {compression!r}")
    if compression == b"gzip" or (compression is None and data[:2] == b"\x1f\x8b"):
        data = gzip.decompress(data)
    elif compression == b"zstd" or (compression is None and data[:4] == b"\x28\xb5\x2f\xfd"):
        if not shutil.which("zstd"):
            raise FixtureError("host zstd is required to unpack the packaged kernel")
        data = subprocess.run(["zstd", "--decompress", "--stdout"], input=data,
                              check=True, stdout=subprocess.PIPE).stdout
    if len(data) < 64 or data[56:60] != b"ARM\x64":
        raise FixtureError("kernel payload is not an arm64 Image")
    image_size = struct.unpack_from("<Q", data, 16)[0]
    if image_size == 0 or len(data) > image_size:
        raise FixtureError("arm64 Image has an invalid declared image size")
    return data


def early_modules(config: Path) -> list[str]:
    """Return the deduplicated force_drivers/add_drivers module list from a conf."""
    text = Path(config).read_text()
    groups = re.findall(r'(?:force_drivers|add_drivers)\+="(.*?)"', text, re.S)
    modules = " ".join(groups).replace("\\", " ").split()
    return list(dict.fromkeys(modules))
