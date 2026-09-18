#!/usr/bin/env python3
"""Replace the DTB in a kboop candidate bundle, writing a new bundle directory.

Like bundle-add-kmods.py, the source bundle is copied first and never modified.
The replacement must keep the same in-bundle path; bundle.json's dtb sha256 and
provenance.json are updated, and the sidecar produced by compose-dtb.py is
referenced (and its base hash checked against the DTB being replaced).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import struct
from pathlib import Path
import shutil
import subprocess
import sys


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import hwe_common

build_kernel = hwe_common


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundler = load_module("fedora_kernel_bundle", TOOLS / "fedora-kernel-bundle.py")
BundleError = bundler.BundleError


def verify_dtb(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise BundleError(f"replacement DTB is not a regular file: {path}")
    data = path.read_bytes()
    if len(data) < 40 or struct.unpack_from(">I", data)[0] != 0xD00DFEED:
        raise BundleError(f"replacement is not a flattened device tree: {path}")
    if struct.unpack_from(">I", data, 4)[0] != len(data):
        raise BundleError(f"replacement DTB declares the wrong size: {path}")


def resolve_bundle(path: Path) -> Path:
    bundle = path / "bundle.json" if path.is_dir() else path
    if bundle.is_symlink() or not bundle.is_file():
        raise BundleError(f"bundle manifest is not a regular file: {bundle}")
    return bundle


def set_dtb(bundle: Path, output: Path, replacement: Path, sidecar: Path | None) -> Path:
    manifest_path = resolve_bundle(bundle)
    source_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    dtb = manifest.get("dtb", {}).get("path")
    if not dtb:
        raise BundleError("source bundle has no dtb entry")
    verify_dtb(replacement)
    if output.exists() or output.is_symlink():
        raise BundleError(f"output already exists; choose a fresh --output: {output}")

    old_sha256 = manifest["dtb"]["sha256"]
    record = {"path": dtb, "source": replacement.name,
              "base_sha256": old_sha256, "sha256": build_kernel.sha256(replacement)}
    if sidecar is not None:
        if sidecar.is_symlink() or not sidecar.is_file():
            raise BundleError(f"sidecar is not a regular file: {sidecar}")
        sidecar_data = json.loads(sidecar.read_text())
        recorded_base = sidecar_data.get("base", {}).get("sha256")
        if recorded_base != old_sha256:
            raise BundleError(
                f"sidecar base {recorded_base} does not match the bundle DTB {old_sha256}")
        record["sidecar"] = {"path": str(sidecar.resolve()), "sha256": build_kernel.sha256(sidecar)}
        record["symbolised_sha256"] = sidecar_data.get("symbolised", {}).get("sha256")
        record["overlays"] = sidecar_data.get("overlays", [])

    shutil.copytree(source_dir, output)
    target = output / dtb
    if target.is_symlink():
        raise BundleError(f"bundle DTB path is a symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(replacement, target)
    if build_kernel.sha256(target) != record["sha256"]:
        raise BundleError("copied DTB changed while exporting")

    manifest["dtb"]["sha256"] = record["sha256"]
    build_kernel.write_json(output / "bundle.json", manifest)

    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
    provenance["dtb"] = record
    provenance["dtb_replaced_at"] = datetime.now(timezone.utc).isoformat()
    artifacts = dict(provenance.get("artifacts", {}))
    artifacts["bundle.json"] = build_kernel.sha256(output / "bundle.json")
    provenance["artifacts"] = artifacts
    build_kernel.write_json(provenance_path, provenance)
    return output / "bundle.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="candidate directory or its bundle.json")
    parser.add_argument("--output", type=Path, required=True, help="new bundle directory")
    parser.add_argument("--dtb", type=Path, required=True, help="replacement DTB file")
    parser.add_argument("--sidecar", type=Path, help="compose-dtb.py sidecar to reference")
    args = parser.parse_args()
    try:
        print(set_dtb(args.bundle, args.output.absolute(), args.dtb.resolve(),
                      args.sidecar.resolve() if args.sidecar else None))
    except (BundleError, build_kernel.BuildError, OSError, ValueError,
            subprocess.CalledProcessError) as error:
        print(f"bundle-set-dtb: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
