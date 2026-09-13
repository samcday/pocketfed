#!/usr/bin/python3
"""Preserve vendored crates' actual license, copyright and notice contents.

Copies every top-level LICENSE/LICENCE/COPYING/COPYRIGHT/NOTICE file or
directory plus every manifest-declared license-file from each vendored crate
into LICENSE.vendor/<crate>/ byte for byte. No text is rewritten. Fails if a
crate has neither readable license notices nor a recognized license-file path.
Missing upstream notices may be supplied under license-supplements/<crate>/;
conflicting contents are rejected instead of overwriting a vendor notice.
"""
from pathlib import Path
import shutil
import sys
import tomllib

PREFIXES = ("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")
OUTPUT = Path("LICENSE.vendor")


def is_readable(path):
    try:
        if path.is_dir():
            next(path.iterdir(), None)
        else:
            with path.open("rb") as handle:
                handle.read(1)
    except OSError:
        return False
    return True


def declared_license_file(crate, manifest):
    declared = manifest.get("package", {}).get("license-file")
    if not declared:
        return None
    candidate = crate / declared
    try:
        candidate.resolve().relative_to(crate.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        destination.mkdir(exist_ok=True)
        for child in sorted(source.iterdir()):
            copy(child, destination / child.name)
    else:
        if destination.exists():
            if not destination.is_file() or source.read_bytes() != destination.read_bytes():
                sys.exit(f"error: conflicting license notice {destination}")
            return
        shutil.copyfile(source, destination)


def main():
    vendor = Path("vendor")
    if not vendor.is_dir():
        sys.exit("error: vendor/ not found; run after cargo vendor")
    failures = []
    for crate in sorted(vendor.iterdir()):
        if not crate.is_dir():
            continue
        manifest = {}
        manifest_path = crate / "Cargo.toml"
        if manifest_path.is_file():
            try:
                manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as error:
                print(f"warning: {crate.name}: unreadable Cargo.toml: {error}", file=sys.stderr)
        notices = [
            entry
            for entry in sorted(crate.iterdir())
            if entry.name.upper().startswith(PREFIXES) and is_readable(entry)
        ]
        declared = declared_license_file(crate, manifest)
        if declared is not None and declared not in notices and is_readable(declared):
            notices.append(declared)
        supplement = Path("license-supplements") / crate.name
        supplemental_notices = [
            entry
            for entry in sorted(supplement.iterdir())
            if entry.name.upper().startswith(PREFIXES) and is_readable(entry)
        ] if supplement.is_dir() else []
        if not notices and not supplemental_notices:
            failures.append(crate.name)
            continue
        for source in notices:
            copy(source, OUTPUT / crate.name / source.relative_to(crate))
        for source in supplemental_notices:
            copy(source, OUTPUT / crate.name / source.relative_to(supplement))
    if failures:
        for name in failures:
            print(f"error: {name}: no license, copyright or notice file found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
