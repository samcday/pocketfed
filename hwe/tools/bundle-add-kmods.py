#!/usr/bin/env python3
"""Add built external kmods to a kboop candidate bundle.

Copies each .ko into the bundle's module tree under updates/<name>/, xz-compresses
it, reruns depmod with the bundle's own System.map, refreshes bundle.json's
module_files inventory and regenerates early-modules.txt. The helper functions
and bundle layout come from fedora-kernel-bundle.py / build-kernel.py.

The source bundle is never modified: the whole tree is copied to --output first.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys


TOOLS = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundler = load_module("fedora_kernel_bundle", TOOLS / "fedora-kernel-bundle.py")
build_kernel = bundler.build_kernel
BundleError = bundler.BundleError


def module_vermagic(path: Path, modinfo: str = "modinfo") -> str:
    result = subprocess.run([modinfo, "-F", "vermagic", str(path)], check=True,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    vermagic = result.stdout.strip()
    if not vermagic:
        raise BundleError(f"modinfo returned no vermagic for {path}")
    return vermagic


def run_depmod(output: Path, release: str, depmod: str = "depmod") -> None:
    commands = build_kernel.Commands(output / "build.log", build_kernel.build_environment())
    log_start = (output / "build.log").stat().st_size if (output / "build.log").exists() else 0
    commands.run([depmod, "-a", "-e", "-F", str(output / "System.map"),
                  "-b", str(output / "modules"), release])
    with (output / "build.log").open("rb") as log:
        log.seek(log_start)
        diagnostics = log.read().decode(errors="replace")
    if "needs unknown symbol" in diagnostics or "ERROR:" in diagnostics:
        raise BundleError("depmod reported unresolved symbols or an error; see build.log")


def resolve_bundle(path: Path) -> Path:
    if path.is_dir():
        bundle = path / "bundle.json"
    else:
        bundle = path
    if bundle.is_symlink() or not bundle.is_file():
        raise BundleError(f"bundle manifest is not a regular file: {bundle}")
    return bundle


def collect_kmods(kmods_dir: Path | None, explicit: list[Path]) -> list[Path]:
    paths = list(explicit)
    if kmods_dir is not None:
        if not kmods_dir.is_dir():
            raise BundleError(f"kmods directory does not exist: {kmods_dir}")
        paths += sorted(kmods_dir.glob("*.ko"))
    if not paths:
        raise BundleError("no .ko modules supplied (use --kmods-dir or --kmod)")
    resolved = []
    for path in paths:
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".ko"):
            raise BundleError(f"expected a regular .ko file: {path}")
        resolved.append(path.resolve())
    return resolved


def load_sources(path: Path | None) -> dict:
    if path is None:
        return {"files": {}, "modules": {}, "kernel_source": {}}
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or "files" not in data or "modules" not in data:
        raise BundleError(f"unsupported sources manifest: {path}")
    return data


def provenance_entry(ko: Path, release_root: Path, name: str, source_key: str,
                     sources: dict, vermagic: str) -> dict:
    relative = (release_root / "updates" / name / (ko.name + ".xz")).relative_to(release_root).as_posix()
    entry = {
        "module": source_key,
        "filename": ko.name,
        "vermagic": vermagic,
        "sha256": build_kernel.sha256(ko),
        "installed": f"lib/modules/{release_root.name}/{relative}",
        "sources": [],
    }
    for source_path in sources.get("modules", {}).get(source_key, []):
        blob = sources.get("files", {}).get(source_path)
        if not blob:
            raise BundleError(f"sources manifest lacks a blob for {source_path}")
        entry["sources"].append({"path": source_path, "blob": blob})
    return entry


def add_kmods(bundle: Path, output: Path, kmods: list[Path], name: str, sources: dict,
              depmod: str = "depmod", modinfo: str = "modinfo") -> Path:
    manifest_path = resolve_bundle(bundle)
    source_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    release = manifest.get("release")
    if not release:
        raise BundleError("source bundle has no release")
    if output.exists() or output.is_symlink():
        raise BundleError(f"output already exists; choose a fresh --output: {output}")

    prepared = []
    for ko in kmods:
        vermagic = module_vermagic(ko, modinfo)
        if vermagic.split()[0] != release:
            raise BundleError(f"{ko.name} vermagic {vermagic!r} does not match bundle release {release!r}")
        source_key = ko.name[:-len(".ko")]
        prepared.append((ko, source_key, vermagic, provenance_entry(
            ko, source_dir / "modules" / "lib" / "modules" / release, name, source_key,
            sources, vermagic)))

    shutil.copytree(source_dir, output)
    release_root = output / "modules" / "lib" / "modules" / release
    if not release_root.is_dir():
        raise BundleError(f"copied bundle lacks {release_root}")
    updates = release_root / "updates" / name
    if updates.exists():
        if updates.is_symlink() or any(updates.iterdir()):
            raise BundleError(f"update directory is not empty: {updates}")
    else:
        updates.mkdir(parents=True)
    for ko, _source_key, _vermagic, _entry in prepared:
        # Match scripts/Makefile.modinst (`xz --check=crc32 --lzma2=dict=1MiB`):
        # the in-kernel decompressor rejects the xz defaults (CRC64, 8 MiB dict)
        # with "decompression failed with status 6".
        (updates / (ko.name + ".xz")).write_bytes(lzma.compress(
            ko.read_bytes(), check=lzma.CHECK_CRC32,
            filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 20}]))

    run_depmod(output, release, depmod)

    for ko, source_key, _vermagic, _entry in prepared:
        installed = f"updates/{name}/{ko.name}.xz"
        if not any(line.startswith(installed + ":") for line in
                   (release_root / "modules.dep").read_text().splitlines()):
            raise BundleError(f"depmod did not index {installed}")

    manifest["module_files"] = build_kernel.inventory(output / "modules")
    build_kernel.write_json(output / "bundle.json", manifest)

    report = bundler.early_module_report(release_root, bundler.REPO / bundler.EARLY_MODULE_CONFIG)
    (output / "early-modules.txt").write_text("".join(f"{mod} {status}\n" for mod, status in report))
    counts = {status: sum(1 for _, value in report if value == status)
              for status in ("present", "builtin", "absent")}
    print(f"early-modules: {counts['present']} present, {counts['builtin']} builtin, "
          f"{counts['absent']} absent ({len(report)} total)", flush=True)

    provenance_path = output / "provenance.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
    provenance.setdefault("kmods", []).extend(entry for _ko, _src, _vm, entry in prepared)
    provenance["kmods_added_at"] = datetime.now(timezone.utc).isoformat()
    provenance["kmods_update_name"] = name
    provenance["kmods_base_bundle"] = str(source_dir)
    provenance["kmods_base_bundle_sha256"] = build_kernel.sha256(manifest_path)
    provenance["module_count"] = len(manifest["module_files"])
    artifacts = dict(provenance.get("artifacts", {}))
    for filename in ("bundle.json", "early-modules.txt", "build.log"):
        target = output / filename
        if target.is_file():
            artifacts[filename] = build_kernel.sha256(target)
    provenance["artifacts"] = artifacts
    build_kernel.write_json(provenance_path, provenance)
    return output / "bundle.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="existing candidate directory or its bundle.json")
    parser.add_argument("--output", type=Path, required=True, help="new bundle directory")
    parser.add_argument("--kmods-dir", type=Path, help="directory containing built .ko files")
    parser.add_argument("--kmod", type=Path, action="append", default=[], help="one built .ko; repeatable")
    parser.add_argument("--name", default="sdm670-early", help="updates/<name>/ destination")
    parser.add_argument("--sources", type=Path, help="sources.json with source blob ids")
    parser.add_argument("--depmod", default="depmod")
    parser.add_argument("--modinfo", default="modinfo")
    args = parser.parse_args()
    try:
        kmods = collect_kmods(args.kmods_dir, args.kmod)
        sources = load_sources(args.sources)
        print(add_kmods(args.bundle, args.output.absolute(), kmods, args.name, sources,
                        args.depmod, args.modinfo))
    except (BundleError, build_kernel.BuildError, OSError, ValueError,
            subprocess.CalledProcessError) as error:
        print(f"bundle-add-kmods: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
