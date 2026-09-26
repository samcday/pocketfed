#!/usr/bin/env python3
"""Build a board DTB as Fedora's own blob plus a series of upstream DTS patches.

Fedora's kernel.spec compiles each DTB from the kernel-ark tag it was built
from. This tool proves that: it compiles the tag's DTS the way
scripts/Makefile.dtbs does and requires the result to be byte-identical to the
blob shipped in kernel-core. Only then does it apply the series with
`git apply` (no fuzz, no three-way) and compile again. The output therefore
differs from Fedora's blob by exactly the patches, which stay in the form they
are submitted upstream.

Nothing is written to --output unless every gate passes. The output never
carries __symbols__, so a vendor DTBO applied by the bootloader cannot resolve
any fixup against it.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class PatchDtbError(Exception):
    pass


CPP_FLAGS = ["-nostdinc", "-undef", "-D__DTS__", "-x", "assembler-with-cpp"]
DTC_WARN_FLAGS = [
    "-Wno-unique_unit_address",
    "-Wno-unit_address_vs_reg",
    "-Wno-avoid_unnecessary_addr_size",
    "-Wno-alias_paths",
    "-Wno-interrupt_map",
    "-Wno-simple_bus_reg",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, text=True, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def checked(argv: list[str], cwd: Path | None = None) -> str:
    result = run(argv, cwd)
    if result.returncode:
        raise PatchDtbError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr}")
    return result.stdout


def compile_dtb(tree: Path, include: Path, dts: str, output: Path, cpp: str, dtc: str) -> None:
    dts_root = tree / "arch/arm64/boot/dts"
    source = dts_root / dts
    if not source.is_file():
        raise PatchDtbError(f"DTS not found in the kernel tree: {source}")
    preprocessed = output.with_suffix(".pre.dts")
    checked([cpp, *CPP_FLAGS, "-I", str(include), "-I", str(dts_root),
             str(source), "-o", str(preprocessed)])
    checked([dtc, "-I", "dts", "-O", "dtb", "-b", "0",
             "-i", str(source.parent), "-i", str(include), "-i", str(dts_root),
             *DTC_WARN_FLAGS, "-o", str(output), str(preprocessed)])


def decompile(dtb: Path, dtc: str) -> list[str]:
    return checked([dtc, "-I", "dtb", "-O", "dts", str(dtb)]).splitlines()


def read_series(series: Path) -> list[Path]:
    patches = []
    for number, line in enumerate(series.read_text().splitlines(), 1):
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        patch = (series.parent / name).resolve()
        if not patch.is_file():
            raise PatchDtbError(f"{series}:{number}: no such patch: {patch}")
        patches.append(patch)
    return patches


def apply_series(tree: Path, patches: list[Path], tag: str) -> None:
    for patch in patches:
        if run(["git", "apply", "--check", str(patch)], tree).returncode == 0:
            checked(["git", "apply", str(patch)], tree)
            continue
        if run(["git", "apply", "--check", "--reverse", str(patch)], tree).returncode == 0:
            raise PatchDtbError(
                f"{patch.name} is already applied in {tag or 'the kernel tree'}: "
                "it has landed upstream, drop it from the series")
        detail = run(["git", "apply", "--check", "--verbose", str(patch)], tree).stderr
        raise PatchDtbError(
            f"{patch.name} does not apply to {tag or 'the kernel tree'}; "
            f"refresh it against that tag\n{detail}")


def build(args: argparse.Namespace) -> dict:
    with tempfile.TemporaryDirectory(prefix="patch-dtb-") as scratch:
        work = Path(scratch)
        reference = work / "reference.dtb"
        compile_dtb(args.kernel_tree, args.include, args.dts, reference, args.cpp, args.dtc)
        if reference.read_bytes() != args.base.read_bytes():
            diff = "\n".join(difflib.unified_diff(
                decompile(args.base, args.dtc), decompile(reference, args.dtc),
                "fedora-blob", f"{args.source_tag or 'kernel-tree'}-compiled", lineterm=""))
            raise PatchDtbError(
                "the kernel tree does not compile to Fedora's blob byte for byte; "
                "check the tag derivation and the dtc version\n" + (diff or "(trees equal, bytes differ)"))

        patches = read_series(args.series)
        tree = work / "tree"
        shutil.copytree(args.kernel_tree / "arch/arm64/boot/dts",
                        tree / "arch/arm64/boot/dts", symlinks=True)
        apply_series(tree, patches, args.source_tag)
        patched = work / "patched.dtb"
        compile_dtb(tree, args.include, args.dts, patched, args.cpp, args.dtc)

        nodes = checked(["fdtget", "-l", str(patched), "/"]).split()
        if "__symbols__" in nodes:
            raise PatchDtbError("patched DTB unexpectedly carries __symbols__")
        if patches and patched.read_bytes() == args.base.read_bytes():
            raise PatchDtbError("the series changed nothing in the compiled DTB")

        report = {
            "source_tag": args.source_tag,
            "dts": args.dts,
            "base_sha256": sha256(args.base),
            "output_sha256": sha256(patched),
            "dtc": checked([args.dtc, "--version"]).strip(),
            "patches": [{"name": patch.name, "sha256": sha256(patch)} for patch in patches],
        }
        # Publish only after every gate passed.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        staged = args.output.with_name(args.output.name + ".tmp")
        shutil.copyfile(patched, staged)
        staged.replace(args.output)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="DTB shipped in Fedora's kernel-core")
    parser.add_argument("--kernel-tree", type=Path, required=True,
                        help="tree holding arch/arm64/boot/dts from the matching kernel-ark tag")
    parser.add_argument("--include", type=Path, required=True,
                        help="include directory with dt-bindings (kernel-devel's include/)")
    parser.add_argument("--dts", required=True, help="DTS path under arch/arm64/boot/dts")
    parser.add_argument("--series", type=Path, required=True, help="ordered list of patch files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="JSON report path")
    parser.add_argument("--source-tag", default="", help="kernel-ark tag the tree came from")
    parser.add_argument("--cpp", default="cpp")
    parser.add_argument("--dtc", default="dtc")
    args = parser.parse_args()
    try:
        report = build(args)
    except (PatchDtbError, OSError) as error:
        print(f"patch-dtb: {error}", file=sys.stderr)
        return 1
    print(f"patch-dtb: {args.dts} + {len(report['patches'])} patches -> {args.output} "
          f"({report['output_sha256'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
