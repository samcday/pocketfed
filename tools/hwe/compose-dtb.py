#!/usr/bin/env python3
"""Compose a boot DTB by applying overlays to a symbolised base blob.

Runs fdtoverlay, then checks the result: the final tree differs from the
symbolised input only by the overlay additions, the debug UART alias and status
are present, and the blob round-trips through dtc. Writes a sidecar with every
input hash and the produced diff.
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


class ComposeError(Exception):
    pass


EXPECTED = (
    ("/aliases", "serial0", "/soc@0/geniqup@ac0000/serial@a90000"),
    ("/soc@0/geniqup@ac0000/serial@a90000", "status", "okay"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], log: list[dict]) -> str:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log.append({"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise ComposeError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr}")
    return result.stdout


def decompile(dtb: Path, dtc: str, log: list[dict]) -> str:
    result = subprocess.run([dtc, "-I", "dtb", "-O", "dts", str(dtb)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log.append({"argv": [dtc, "-I", "dtb", "-O", "dts", str(dtb)], "returncode": result.returncode,
                "stdout": "", "stderr": result.stderr})
    if result.returncode:
        raise ComposeError(f"dtc could not decompile {dtb}: {result.stderr}")
    return result.stdout


def regular(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ComposeError(f"{label} is not a regular file: {path}")
    return path


def compose(args: argparse.Namespace) -> Path:
    base = regular(args.base.resolve(), "--base")
    symbolised = regular(args.symbolised.resolve(), "--symbolised")
    overlays = [regular(path.resolve(), "--overlay") for path in args.overlay]
    if not overlays:
        raise ComposeError("at least one --overlay is required")
    output = args.output.absolute()
    sidecar = args.sidecar.absolute()
    if output.exists() or output.is_symlink():
        raise ComposeError(f"output already exists: {output}")
    if sidecar.exists() or sidecar.is_symlink():
        raise ComposeError(f"sidecar already exists: {sidecar}")

    log: list[dict] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    run([args.fdtoverlay, "-i", str(symbolised), "-o", str(output), *map(str, overlays)], log)

    diff = "\n".join(difflib.unified_diff(
        decompile(symbolised, args.dtc, log).splitlines(),
        decompile(output, args.dtc, log).splitlines(),
        "symbolised", "final", lineterm=""))

    checks = []
    for node, prop, expected in EXPECTED:
        value = run([args.fdtget, "-t", "s", str(output), node, prop], log).strip()
        checks.append({"path": f"{node}/{prop}", "expected": expected, "actual": value,
                       "pass": value == expected})
    if not all(check["pass"] for check in checks):
        raise ComposeError("fdtget checks failed: " + json.dumps(checks))

    work = Path(tempfile.mkdtemp(prefix=".compose-", dir=output.parent))
    try:
        round_trip_dtb = work / "round-trip.dtb"
        final_dts = decompile(output, args.dtc, log)
        (work / "final.dts").write_text(final_dts)
        run([args.dtc, "-I", "dts", "-O", "dtb", "-o", str(round_trip_dtb), str(work / "final.dts")], log)
        round_trip = decompile(round_trip_dtb, args.dtc, log) == final_dts
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if not round_trip:
        raise ComposeError("final blob did not round-trip through dtc")

    record = {
        "schema_version": 1,
        "base": {"path": str(base), "sha256": sha256(base)},
        "symbolised": {"path": str(symbolised), "sha256": sha256(symbolised)},
        "overlays": [{"path": str(path), "sha256": sha256(path)} for path in overlays],
        "output": {"path": str(output), "sha256": sha256(output)},
        "symbolise_report": ({"path": str(args.symbolise_report.resolve()),
                              "sha256": sha256(args.symbolise_report.resolve())}
                             if args.symbolise_report else None),
        "fdtget": checks,
        "round_trip": round_trip,
        "diff_vs_symbolised": diff,
        "commands": log,
    }
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="Fedora-built base DTB")
    parser.add_argument("--symbolised", type=Path, required=True, help="symbolised base DTB")
    parser.add_argument("--overlay", type=Path, action="append", required=True, help="compiled .dtbo; repeatable")
    parser.add_argument("--output", type=Path, required=True, help="new final DTB")
    parser.add_argument("--sidecar", type=Path, required=True, help="JSON sidecar path")
    parser.add_argument("--symbolise-report", type=Path, help="symbolise report to reference")
    parser.add_argument("--dtc", default="dtc")
    parser.add_argument("--fdtoverlay", default="fdtoverlay")
    parser.add_argument("--fdtget", default="fdtget")
    args = parser.parse_args()
    try:
        print(compose(args))
    except (ComposeError, OSError, ValueError) as error:
        print(f"compose-dtb: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
