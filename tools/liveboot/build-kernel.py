#!/usr/bin/env python3
"""Incrementally build an arm64 kernel and seal a kboop version-1 bundle.

Use an already configured Kbuild output directory. Nothing is installed on the
host or phone; modules_install always targets a new candidate directory. Keep
one build directory per source/configuration lane and one output per experiment.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
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
import sys
import time


class BuildError(Exception):
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


def capture(argv: list[str], *, cwd: Path | None = None) -> bytes:
    return subprocess.run(argv, cwd=cwd, check=True, stdout=subprocess.PIPE).stdout


def source_state(tree: Path, excluded: tuple[Path, ...]) -> tuple[dict, bytes]:
    root = Path(os.fsdecode(capture(["git", "rev-parse", "--show-toplevel"], cwd=tree)).strip()).resolve()
    if root != tree:
        raise BuildError("--kernel-tree must be the root of its own Git source checkout")
    commit = capture(["git", "rev-parse", "HEAD"], cwd=tree).decode().strip()
    patch = capture(["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", "."], cwd=tree)
    untracked = {}
    for raw in capture(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=tree).split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = tree / name
        if any(path == omit or omit in path.parents for omit in excluded):
            continue
        if path.is_symlink():
            untracked[name] = {"symlink": os.readlink(path)}
        else:
            regular(path, empty=True)
            untracked[name] = {"sha256": sha256(path)}
    submodules = capture(["git", "submodule", "status", "--recursive"], cwd=tree).decode().splitlines()
    if submodules:
        raise BuildError("kernel source submodules are not supported; use a self-contained kernel checkout")
    return {"path": str(tree), "commit": commit, "dirty_patch_sha256": hashlib.sha256(patch).hexdigest(),
            "dirty": bool(patch or untracked), "untracked": untracked,
            "untracked_note": "Hashes/targets only; preserve any untracked source files separately."}, patch


def make_variables(items: list[str]) -> dict[str, str]:
    result = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or key not in MAKE_VARIABLES or "\0" in value or "\n" in value:
            raise BuildError(f"unsupported --make-var {item!r}; supported names: {', '.join(sorted(MAKE_VARIABLES))}")
        if key in result:
            raise BuildError(f"duplicate --make-var: {key}")
        result[key] = value
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


def built_module_inventory(build: Path, order: Path) -> dict[str, str]:
    result = {}
    for line in order.read_text().splitlines():
        relative(line)
        if not line.endswith((".o", ".ko")):
            raise BuildError(f"unexpected entry in modules.order: {line}")
        name = line[:-2] + ".ko" if line.endswith(".o") else line
        path = safe_child(build, name)
        regular(path)
        if name in result:
            raise BuildError(f"duplicate entry in modules.order: {line}")
        result[name] = sha256(path)
    return result


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


def produce(args: argparse.Namespace) -> Path:
    tree, build = args.kernel_tree.resolve(), args.build_dir.resolve()
    output = args.output.absolute()
    dtb = relative(args.dtb).as_posix()
    if not dtb.endswith(".dtb"):
        raise BuildError("--dtb must be a path below arch/arm64/boot/dts ending in .dtb")
    regular(tree / "Makefile")
    regular(build / ".config")
    variables = make_variables(args.make_var)
    if args.llvm is not None:
        if "LLVM" in variables:
            raise BuildError("use either --llvm or --make-var LLVM=..., not both")
        variables["LLVM"] = args.llvm
    # Kbuild represents O= paths in generated make syntax and cannot handle whitespace.
    if any(re.search(r"[\s#$:%]", str(p)) for p in (tree, build, output)):
        raise BuildError("Kbuild source, build, and output paths must not contain whitespace or # $ : %")
    if output.exists() or output.is_symlink():
        raise BuildError(f"candidate already exists; choose a fresh --output: {output}")
    if build != tree:
        associated_source = build / "source"
        if associated_source.is_symlink():
            if associated_source.resolve() != tree:
                raise BuildError("build/source points to another kernel tree; use that tree or a separate build directory")
        elif args.no_build:
            raise BuildError("--no-build requires an existing Kbuild source link matching --kernel-tree")
    output.mkdir(parents=True)
    commands = Commands(output / "build.log", build_environment())
    provenance = {"schema_version": 1, "producer": "pocketfed/tools/liveboot/build-kernel.py",
                  "producer_sha256": sha256(Path(__file__)), "build_dir": str(build),
                  "build_requested": not args.no_build,
                  "no_build_note": "Observed source state is not proof that pre-existing outputs were compiled from it." if args.no_build else None,
                  "make_variables": variables, "cross_compile": args.cross_compile,
                  "tool_search_path": commands.env.get("PATH", ""),
                  "commands": commands.records}
    try:
        with (build / ".pocketfed-liveboot-build.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BuildError("another liveboot producer is using this build directory") from error
            excluded = tuple(path for path in (build, output) if path != tree)
            source, patch = source_state(tree, excluded)
            provenance["source"] = source
            (output / "source.patch").write_bytes(patch)
            make = [args.make, "--no-print-directory", "-s", "-C", str(tree), f"O={build}", "ARCH=arm64",
                    f"CROSS_COMPILE={args.cross_compile}", *[f"{k}={v}" for k, v in sorted(variables.items())]]
            for label, argv in (("make", [args.make, "--version"]), ("depmod", [args.depmod, "--version"]),
                                ("modinfo", [args.modinfo, "--version"])):
                provenance.setdefault("tools", {})[label] = commands.run(argv, stdout=True)
            if not args.no_build:
                print(f"Incremental build; log: {output / 'build.log'}", flush=True)
                commands.run([*make, f"-j{args.jobs}", "Image.gz", dtb, "modules"])
            regular(build / "include/config/kernel.release")
            release = (build / "include/config/kernel.release").read_text().strip()
            queried = commands.run([*make, "kernelrelease"], stdout=True)
            if queried != release:
                raise BuildError(f"stored and queried kernelrelease differ ({release!r} vs {queried!r}); rebuild first")
            paths = verify_kernel(build, dtb, release)
            before = {key: sha256(path) for key, path in paths.items()}
            built_modules = built_module_inventory(build, paths["modules_order"])
            provenance["built_module_files"] = built_modules
            provenance["release"] = release
            compile_h = build / "include/generated/compile.h"
            regular(compile_h)
            provenance["compiled_toolchain"] = compile_h.read_text()
            for key, destination in (("image", "Image.gz"), ("dtb", dtb), ("config", "kernel.config"),
                                     ("system_map", "System.map")):
                target = output / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(paths[key], target)
            install = output / "modules"
            # DEPMOD=true avoids the kernel wrapper silently skipping missing tools.
            # Explicit depmod below always produces metadata using this System.map.
            commands.run([*make, f"-j{args.jobs}", f"INSTALL_MOD_PATH={install}", "DEPMOD=true", "modules_install"])
            depmod_log_start = commands.log.stat().st_size
            commands.run([args.depmod, "-a", "-e", "-F", str(output / "System.map"), "-b", str(install), release])
            with commands.log.open("rb") as log:
                log.seek(depmod_log_start)
                diagnostics = log.read().decode(errors="replace")
            if "needs unknown symbol" in diagnostics or "ERROR:" in diagnostics:
                raise BuildError("depmod reported unresolved symbols or an error; see build.log")
            module_files = verify_modules(install, release, paths["modules_order"], commands, args.modinfo)
            after = {key: sha256(path) for key, path in paths.items()}
            source_after, _ = source_state(tree, excluded)
            if before != after or source_after != source or built_modules != built_module_inventory(build, paths["modules_order"]):
                raise BuildError("source or build inputs changed during export; use an idle build directory and retry")
            manifest = {"schema_version": 1, "release": release,
                        "image": {"path": "Image.gz", "sha256": sha256(output / "Image.gz")},
                        "dtb": {"path": dtb, "sha256": sha256(output / dtb)},
                        "modules_install": "modules", "module_files": module_files}
            write_json(output / "bundle.json", manifest)
            provenance["artifacts"] = {name: sha256(output / name) for name in
                                       ("bundle.json", "kernel.config", "System.map", "source.patch", "build.log")}
            provenance["completed_at"] = datetime.now(timezone.utc).isoformat()
            write_json(output / "provenance.json", provenance)
    except (BuildError, OSError, ValueError, subprocess.CalledProcessError) as error:
        provenance["error"] = str(error)
        write_json(output / "failure.json", provenance)
        raise BuildError(str(error)) from error
    return output / "bundle.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-tree", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True, help="existing Kbuild output with a configured .config")
    parser.add_argument("--output", type=Path, required=True, help="new, immutable candidate directory")
    parser.add_argument("--dtb", required=True, help="e.g. qcom/sdm670-google-sargo.dtb (below arch/arm64/boot/dts)")
    parser.add_argument("--cross-compile", default="aarch64-linux-gnu-", help="GCC/binutils cross prefix; use empty for native ARM64")
    parser.add_argument("--llvm", nargs="?", const="1", help="Kbuild LLVM value, optionally a tool path or version suffix")
    parser.add_argument("--make-var", action="append", default=[], metavar="NAME=VALUE", help="explicit toolchain/flags/local-version Kbuild variable; repeatable")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--no-build", action="store_true", help="reuse completed build outputs; still run modules_install and depmod")
    parser.add_argument("--make", default="make")
    parser.add_argument("--depmod", default="depmod")
    parser.add_argument("--modinfo", default="modinfo")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        print(produce(args))
    except (BuildError, OSError, subprocess.CalledProcessError) as error:
        print(f"build-kernel: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
