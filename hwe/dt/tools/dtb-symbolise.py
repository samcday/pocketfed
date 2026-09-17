#!/usr/bin/env python3
"""Reconstitute __symbols__ (and missing phandles) in a Fedora-built DTB.

Fedora's kernel.spec runs plain `make dtbs`, so sargo's blob has no __symbols__.
We compile the exact DTS from the matching kernel-ark tag with `dtc -@`, prove
the two blobs are equivalent apart from symbols/labels/phandles, then inject the
symbol table and any phandles the base lacks. Existing phandles are never
renumbered.

The DTS is preprocessed with cpp and compiled with dtc exactly as
scripts/Makefile.dtbs does for `make dtbs` (plus `-@`).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import libfdt


class SymboliseError(Exception):
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
SYMBOL_NODES = ("__symbols__", "__fixups__", "__local_fixups__")
LABEL_PREFIX = re.compile(r"^(\s*)[A-Za-z_][A-Za-z0-9_]*:\s+(.*)$")
PHANDLE_PROPERTY = re.compile(r"^\s*phandle\s*=\s*<0x[0-9a-fA-F]+>;\s*$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_include_paths(kernel_tree: Path) -> list[str]:
    return [
        str(kernel_tree / "scripts/dtc/include-prefixes"),
        str(kernel_tree / "include"),
        str(kernel_tree / "arch/arm64/boot/dts"),
    ]


def run_logged(argv: list[str], log: list[dict]) -> None:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log.append({"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise SymboliseError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr}")


def preprocess(kernel_tree: Path, dts: Path, output: Path, cpp: str, log: list[dict]) -> None:
    argv = [cpp, *CPP_FLAGS]
    for directory in compile_include_paths(kernel_tree):
        argv += ["-I", directory]
    argv += [str(dts), "-o", str(output)]
    run_logged(argv, log)


def compile_dts(kernel_tree: Path, preprocessed: Path, dts_dir: Path, output: Path,
                dtc: str, symbols: bool, log: list[dict]) -> None:
    argv = [dtc, "-I", "dts", "-O", "dtb", "-b", "0"]
    if symbols:
        argv.append("-@")
    for directory in (dts_dir, *map(Path, compile_include_paths(kernel_tree))):
        argv += ["-i", str(directory)]
    argv += DTC_WARN_FLAGS
    argv += ["-o", str(output), str(preprocessed)]
    run_logged(argv, log)


def decompile(dtb: Path, dtc: str, log: list[dict]) -> str:
    argv = [dtc, "-I", "dtb", "-O", "dts", str(dtb)]
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log.append({"argv": argv, "returncode": result.returncode,
                "stdout": "", "stderr": result.stderr})
    if result.returncode:
        raise SymboliseError(f"dtc could not decompile {dtb}: {result.stderr}")
    return result.stdout


def _drop_node(lines: list[str], index: int) -> int:
    indent = re.match(r"^(\s*)", lines[index]).group(1)
    index += 1
    while index < len(lines) and lines[index].rstrip() != indent + "};":
        index += 1
    return index + 1


def normalize(text: str) -> str:
    """Text-normalise a decompiled DTB for equivalence comparison.

    Compiling with -@ emits node/property labels and assigns extra phandles;
    the gate must compare only the actual tree. Blank lines are cosmetic.
    """
    lines = text.splitlines()
    result = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\s*__(\w+)__\s*\{\s*$", line)
        if match and ("__" + match.group(1) + "__") in SYMBOL_NODES:
            index = _drop_node(lines, index)
            continue
        if PHANDLE_PROPERTY.match(line):
            index += 1
            continue
        line = LABEL_PREFIX.sub(r"\1\2", line)
        if line.strip():
            result.append(line.rstrip())
        index += 1
    return "\n".join(result) + "\n"


def equivalence(base_dtb: Path, reference_dtb: Path, dtc: str) -> tuple[bool, str, list[dict]]:
    log: list[dict] = []
    base = normalize(decompile(base_dtb, dtc, log))
    reference = normalize(decompile(reference_dtb, dtc, log))
    if base == reference:
        return True, "", log
    diff = "\n".join(difflib.unified_diff(
        base.splitlines(), reference.splitlines(), "fedora-base", "kernel-tree-reference", lineterm=""))
    return False, diff, log


def read_symbols(reference_dtb: Path) -> list[tuple[str, str]]:
    fdt = libfdt.Fdt(reference_dtb.read_bytes())
    try:
        offset = fdt.path_offset("/__symbols__")
    except libfdt.FdtException as error:
        raise SymboliseError("reference blob has no /__symbols__; was it compiled with -@?") from error
    symbols = []
    prop_offset = fdt.first_property_offset(offset)
    while True:
        prop = fdt.get_property_by_offset(prop_offset)
        symbols.append((prop.name, prop.as_str()))
        try:
            prop_offset = fdt.next_property_offset(prop_offset)
        except libfdt.FdtException:
            break
    return symbols


def _walk(fdt, offset: int, visit) -> None:
    visit(offset)
    try:
        child = fdt.first_subnode(offset)
    except libfdt.FdtException:
        return
    while child >= 0:
        _walk(fdt, child, visit)
        try:
            child = fdt.next_subnode(child)
        except libfdt.FdtException:
            break


def max_phandle(fdt) -> int:
    top = [0]

    def visit(offset: int) -> None:
        if fdt.hasprop(offset, "phandle"):
            top[0] = max(top[0], fdt.getprop(offset, "phandle").as_uint32())

    _walk(fdt, 0, visit)
    return top[0]


def inject_symbols(base_bytes: bytes, symbols: list[tuple[str, str]]) -> tuple[bytes, list[dict]]:
    fdt = libfdt.Fdt(bytearray(base_bytes))
    fdt.resize(len(base_bytes) + 128 * 1024)
    next_phandle = max_phandle(fdt) + 1
    added: list[dict] = []
    for label, path in symbols:
        try:
            offset = fdt.path_offset(path)
        except libfdt.FdtException as error:
            raise SymboliseError(f"symbol {label!r} path {path!r} is absent from the base blob") from error
        if offset < 0:
            raise SymboliseError(f"symbol {label!r} path {path!r} is absent from the base blob")
        if not fdt.hasprop(offset, "phandle"):
            fdt.setprop_u32(offset, "phandle", next_phandle)
            added.append({"label": label, "path": path, "phandle": next_phandle})
            next_phandle += 1
    try:
        symbols_offset = fdt.path_offset("/__symbols__")
    except libfdt.FdtException:
        symbols_offset = fdt.add_subnode(0, "__symbols__")
    for label, path in symbols:
        fdt.setprop_str(symbols_offset, label, path)
    fdt.pack()
    return bytes(fdt.as_bytearray()), added


def source_state(kernel_tree: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(kernel_tree), *args], check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()

    return {"worktree": str(kernel_tree), "commit": git("rev-parse", "HEAD"),
            "tag": git("describe", "--tags", "--exact-match")}


def symbolise(args: argparse.Namespace) -> Path:
    kernel_tree = args.kernel_tree.resolve()
    base = args.base.resolve()
    output = args.output.absolute()
    report_path = args.report.absolute()
    dts_relative = Path(args.dts)
    if dts_relative.is_absolute() or ".." in dts_relative.parts:
        raise SymboliseError("--dts must be a relative path under arch/arm64/boot/dts")
    dts = kernel_tree / "arch/arm64/boot/dts" / dts_relative
    if not dts.is_file() or dts.is_symlink():
        raise SymboliseError(f"no such DTS: {dts}")
    for path in (base,):
        if path.is_symlink() or not path.is_file():
            raise SymboliseError(f"missing input: {path}")
    if output.exists() or output.is_symlink():
        raise SymboliseError(f"output already exists: {output}")
    if report_path.exists() or report_path.is_symlink():
        raise SymboliseError(f"report already exists: {report_path}")

    compile_log: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix=".symbolise-", dir=output.parent))
    try:
        preprocessed = work / "reference.pre.dts"
        reference = work / "reference.dtb"
        preprocess(kernel_tree, dts, preprocessed, args.cpp, compile_log)
        compile_dts(kernel_tree, preprocessed, dts.parent, reference, args.dtc, True, compile_log)
        equivalent, diff, gate_log = equivalence(base, reference, args.dtc)
        compile_log += gate_log
        report = {
            "schema_version": 1,
            "base": {"path": str(base), "sha256": sha256(base)},
            "reference": {"dtb": str(reference), "sha256": sha256(reference),
                          "dts": str(dts), "dts_sha256": sha256(dts)},
            "kernel_source": source_state(kernel_tree),
            "equivalence": {"pass": equivalent, "diff": diff,
                            "normalised_base_sha256": hashlib.sha256(
                                normalize(decompile(base, args.dtc, [])).encode()).hexdigest(),
                            "normalised_reference_sha256": hashlib.sha256(
                                normalize(decompile(reference, args.dtc, [])).encode()).hexdigest()},
            "commands": compile_log,
        }
        if not equivalent:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            raise SymboliseError("equivalence gate failed; see the report diff")
        symbols = read_symbols(reference)
        output.parent.mkdir(parents=True, exist_ok=True)
        symbolised, added = inject_symbols(base.read_bytes(), symbols)
        output.write_bytes(symbolised)
        report["symbols"] = {"count": len(symbols),
                             "labels": [label for label, _ in symbols]}
        report["phandles"] = {"max_existing": max_phandle(libfdt.Fdt(base.read_bytes())),
                              "added_count": len(added), "added": added}
        report["output"] = {"path": str(output), "sha256": sha256(output)}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return output
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="Fedora-built DTB")
    parser.add_argument("--kernel-tree", type=Path, required=True, help="exact kernel source worktree")
    parser.add_argument("--dts", required=True, help="DTS path under arch/arm64/boot/dts")
    parser.add_argument("--output", type=Path, required=True, help="new symbolised DTB")
    parser.add_argument("--report", type=Path, required=True, help="JSON report path")
    parser.add_argument("--cpp", default="cpp")
    parser.add_argument("--dtc", default="dtc")
    args = parser.parse_args()
    try:
        print(symbolise(args))
    except (SymboliseError, OSError, ValueError) as error:
        print(f"dtb-symbolise: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
