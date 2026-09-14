#!/usr/bin/env python3
"""Build or audit a local PocketFed keyboard-trial bundle.

`build` compiles the pinned Stevia client and Verbisage service from exact clean
local checkouts, stages the three trial binaries and the matching OSK GSettings
schema into a NEW output directory, records a manifest and rejects architecture
mismatches. `audit` re-checks a produced bundle against its manifest.

This is a source/build helper only. It never touches a device, package set,
image, container or pre-existing output, and it does not start or restart
anything. Commands are executed as explicit argument vectors; no shell string is
interpolated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = HERE / "sources.json"
ARCHES = ("x86_64", "aarch64")
ELF_MACHINES = {0x03: "x86", 0x28: "arm", 0x3E: "x86_64", 0xB7: "aarch64"}
HOST_ALIASES = {"amd64": "x86_64", "arm64": "aarch64"}
BINARIES = ("phosh-osk-stevia", "verbisaged", "verbisage")
SCHEMA_FILES = ("mobi.phosh.osk.gschema.xml", "mobi.phosh.osk.enums.xml")
SCHEMA_DIR = "share/glib-2.0/schemas"
BINARY_ARTIFACTS = tuple(f"bin/{name}" for name in BINARIES)
SCHEMA_ARTIFACTS = tuple(f"{SCHEMA_DIR}/{name}" for name in SCHEMA_FILES + ("gschemas.compiled",))
EXPECTED_ARTIFACTS = BINARY_ARTIFACTS + SCHEMA_ARTIFACTS
ELF_MACHINE_CODES = {"x86_64": 0x3E, "aarch64": 0xB7}


def run(argv, cwd=None, env=None):
    print("+ " + " ".join(shlex.quote(str(a)) for a in argv), flush=True)
    subprocess.run([str(a) for a in argv], cwd=cwd, env=env, check=True)


def capture(argv):
    try:
        return subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable: {exc}"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def elf_machine(path):
    with Path(path).open("rb") as handle:
        data = handle.read(20)
    if data[:4] != b"\x7fELF" or len(data) < 20:
        raise SystemExit(f"{path}: not an ELF executable")
    endian = "<" if data[5] == 1 else ">"
    (machine,) = struct.unpack_from(endian + "H", data, 18)
    return ELF_MACHINES.get(machine, f"0x{machine:02x}")


def host_arch():
    return HOST_ALIASES.get(os.uname().machine, os.uname().machine)


def toolchain():
    cc = capture(["cc", "--version"])
    return {
        "cc": cc.splitlines()[0] if cc else "",
        "meson": capture(["meson", "--version"]),
        "ninja": capture(["ninja", "--version"]),
        "cargo": capture(["cargo", "--version"]),
        "rustc": capture(["rustc", "--version"]),
        "glib-compile-schemas": capture(["glib-compile-schemas", "--version"]),
        "host_arch": host_arch(),
    }


def load_pins():
    data = json.loads(PINS.read_text())
    if data.get("schema_version") != 1:
        raise SystemExit(f"unsupported pins schema in {PINS}")
    return data


def verify_checkouts(sources_root, pins, require_clean):
    verified = {}
    for name, pin in pins["sources"].items():
        repo = sources_root / pin["path"]
        if not (repo / ".git").exists():
            raise SystemExit(f"{name}: no checkout at {repo}")
        head = git(repo, "rev-parse", "HEAD")
        if head != pin["commit"]:
            raise SystemExit(
                f"{name}: HEAD {head} does not match pin {pin['commit']} ({repo})"
            )
        if require_clean:
            dirty = git(repo, "status", "--porcelain")
            if dirty:
                raise SystemExit(
                    f"{name}: checkout is not clean; commit/stash changes or pass "
                    f"--export-commits to build from the pinned commits:\n{dirty}"
                )
        verified[name] = {"path": pin["path"], "commit": head}
    return verified


def export_commits(sources_root, dest, pins, order):
    """Materialise the pinned commits into a fresh sibling layout via git archive."""
    dest.mkdir(parents=True)
    for name in order:
        pin = pins["sources"][name]
        repo = sources_root / pin["path"]
        target = dest / pin["path"]
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.Popen(
            ["git", "-C", str(repo), "archive", "--format=tar", pin["commit"]],
            stdout=subprocess.PIPE,
        )
        assert archive.stdout is not None
        with tarfile.open(fileobj=archive.stdout, mode="r|") as tar:
            tar.extractall(target, filter="data")
        archive.stdout.close()
        if archive.wait() != 0:
            raise SystemExit(f"{name}: git archive of {pin['commit']} failed")
        print(f"exported {name} {pin['commit']} -> {target}", flush=True)
    return dest


def build_stevia(sources_root, build_root, args):
    source = sources_root / "stevia"
    build = build_root / "stevia-build"
    if build.exists():
        raise SystemExit(f"refusing to reuse existing Stevia build dir: {build}")
    setup = [
        "meson", "setup", str(build), str(source),
        "--buildtype=debugoptimized",
        "-Dtests=true", "-Dgtk_doc=false", "-Dman=false", "-Ddefault_osk=true",
    ]
    if args.meson_cross_file:
        setup += ["--cross-file", str(args.meson_cross_file)]
    run(setup)
    run(["meson", "compile", "-C", str(build)])
    binary = build / "src" / "phosh-osk-stevia"
    schema = build / "data" / "mobi.phosh.osk.gschema.xml"
    enums = build / "data" / "mobi.phosh.osk.enums.xml"
    for path in (binary, schema, enums):
        if not path.is_file():
            raise SystemExit(f"expected Stevia artifact missing: {path}")
    return {
        "binary": binary,
        "schema": schema,
        "enums": enums,
        "options": {"buildtype": "debugoptimized", "tests": True, "gtk_doc": False,
                    "man": False, "default_osk": True},
        "build_dir": str(build),
    }


def build_verbisage(sources_root, build_root, args):
    manifest = sources_root / "verbisage" / "Cargo.toml"
    target_dir = (Path(args.cargo_target_dir) if args.cargo_target_dir
                  else build_root / "verbisage-target")
    env = dict(os.environ, CARGO_TARGET_DIR=str(target_dir))
    command = ["cargo", "build", "--manifest-path", str(manifest),
               "--release", "--all-features", "--locked"]
    if args.cargo_target:
        command += ["--target", args.cargo_target]
    run(command, env=env)
    output = target_dir / (args.cargo_target or "") / "release"
    binaries = {}
    for name in ("verbisaged", "verbisage"):
        path = output / name
        if not path.is_file():
            raise SystemExit(f"expected Verbisage artifact missing: {path}")
        binaries[name] = path
    return {
        "binaries": binaries,
        "target_dir": str(target_dir),
        "profile": "release",
        "features": "all",
        "cargo_target": args.cargo_target,
    }


def stage(output, stevia, verbisage, args):
    bin_dir = output / "bin"
    schema_dir = output / SCHEMA_DIR
    bin_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)
    artifacts = {}
    for name in BINARIES:
        source = stevia["binary"] if name == "phosh-osk-stevia" else verbisage["binaries"][name]
        target = bin_dir / name
        shutil.copy2(source, target)
        machine = elf_machine(target)
        if machine != args.arch:
            raise SystemExit(
                f"architecture mismatch for {name}: built {machine}, expected {args.arch}"
            )
        artifacts[f"bin/{name}"] = {"sha256": sha256(target), "elf_machine": machine,
                                    "size": target.stat().st_size}
    shutil.copy2(stevia["schema"], schema_dir / SCHEMA_FILES[0])
    shutil.copy2(stevia["enums"], schema_dir / SCHEMA_FILES[1])
    run(["glib-compile-schemas", str(schema_dir)])
    compiled = schema_dir / "gschemas.compiled"
    if not compiled.is_file():
        raise SystemExit(f"glib-compile-schemas did not produce {compiled}")
    artifacts[f"{SCHEMA_DIR}/gschemas.compiled"] = {
        "sha256": sha256(compiled), "size": compiled.stat().st_size}
    for name in SCHEMA_FILES:
        path = schema_dir / name
        artifacts[f"{SCHEMA_DIR}/{name}"] = {
            "sha256": sha256(path), "size": path.stat().st_size}
    return artifacts


def write_manifest(output, args, pins, verified, stevia, verbisage, artifacts):
    manifest = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "arch": args.arch,
        "toolchain": toolchain(),
        "sources": {
            name: {
                "commit": record["commit"],
                "path": record["path"],
                "retrieval": pins["sources"][name]["retrieval"],
                "public_pr": pins["sources"][name].get("public_pr"),
                "private": pins["sources"][name].get("private", False),
            }
            for name, record in verified.items()
        },
        "build": {
            "stevia": stevia["options"] | {"build_dir": stevia["build_dir"]},
            "verbisage": {"profile": verbisage["profile"], "features": verbisage["features"],
                          "target_dir": verbisage["target_dir"],
                          "cargo_target": verbisage["cargo_target"]},
        },
        "artifacts": artifacts,
    }
    (output / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def _is_digest(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _artifact_record(path, is_binary):
    if not isinstance(path, dict):
        raise SystemExit("artifact record is not an object")
    for key in ("sha256", "size"):
        if key not in path:
            raise SystemExit(f"artifact record has no {key}")
    if not _is_digest(path["sha256"]):
        raise SystemExit("artifact record sha256 is not a 64-character hex digest")
    if not isinstance(path["size"], int) or isinstance(path["size"], bool) or path["size"] < 0:
        raise SystemExit("artifact record size is not a non-negative integer")
    if is_binary and not isinstance(path.get("elf_machine"), str):
        raise SystemExit("binary artifact record has no elf_machine")
    return path


def audit_bundle(bundle, arch, pins=None):
    manifest_path = bundle / "bundle-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no bundle-manifest.json in {bundle}")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise SystemExit("bundle manifest is not an object")
    if manifest.get("schema_version") != 1:
        raise SystemExit(
            f"unsupported bundle manifest schema_version {manifest.get('schema_version')!r}")
    if manifest.get("arch") not in ARCHES:
        raise SystemExit(f"bundle manifest arch {manifest.get('arch')!r} is not supported")
    if manifest["arch"] != arch:
        raise SystemExit(
            f"bundle arch {manifest['arch']!r} does not match requested {arch!r}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("bundle manifest artifacts is not an object")
    recorded = set(artifacts)
    expected = set(EXPECTED_ARTIFACTS)
    missing = sorted(expected - recorded)
    unexpected = sorted(recorded - expected)
    if missing:
        raise SystemExit(f"bundle manifest is missing artifact records: {', '.join(missing)}")
    if unexpected:
        raise SystemExit(f"bundle manifest has unexpected artifact records: {', '.join(unexpected)}")
    for rel in EXPECTED_ARTIFACTS:
        is_binary = rel in BINARY_ARTIFACTS
        record = _artifact_record(artifacts[rel], is_binary)
        path = bundle / rel
        if not path.is_file():
            raise SystemExit(f"artifact listed but absent: {rel}")
        size = path.stat().st_size
        if size != record["size"]:
            raise SystemExit(f"{rel}: size {size} != manifest {record['size']}")
        actual = sha256(path)
        if actual != record["sha256"]:
            raise SystemExit(f"{rel}: sha256 {actual} != manifest {record['sha256']}")
        if is_binary:
            # Inspect the file directly; do not trust the manifest's cached value.
            machine = elf_machine(path)
            if machine != arch:
                raise SystemExit(f"{rel}: ELF machine {machine} != {arch}")
            if record["elf_machine"] != machine:
                raise SystemExit(
                    f"{rel}: manifest elf_machine {record['elf_machine']!r} != inspected {machine!r}")
    if pins is not None:
        for name, pin in pins["sources"].items():
            recorded = manifest.get("sources", {}).get(name, {}).get("commit")
            if recorded != pin["commit"]:
                raise SystemExit(
                    f"{name}: manifest source {recorded} != pin {pin['commit']}")
    print(f"audit ok: {bundle} ({arch}, {len(EXPECTED_ARTIFACTS)} artifacts, "
          f"{len(BINARIES)} binaries)", flush=True)
    return manifest


def minimal_elf(machine):
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(8)
    return ident + struct.pack("<HHIQQQIHHHHHH", 2, machine, 1, 0, 0, 0, 0, 64,
                               0, 0, 0, 0, 0)


def synthetic_bundle(dest, arch):
    (dest / "bin").mkdir(parents=True)
    (dest / SCHEMA_DIR).mkdir(parents=True)
    artifacts = {}
    for rel in BINARY_ARTIFACTS:
        data = minimal_elf(ELF_MACHINE_CODES[arch])
        (dest / rel).write_bytes(data)
        artifacts[rel] = {"sha256": hashlib.sha256(data).hexdigest(),
                          "size": len(data), "elf_machine": arch}
    for rel in SCHEMA_ARTIFACTS:
        data = f"<{Path(rel).name}>\n".encode()
        (dest / rel).write_bytes(data)
        artifacts[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    manifest = {"schema_version": 1, "arch": arch, "artifacts": artifacts}
    (dest / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def _rewrite_manifest(bundle, mutate):
    path = bundle / "bundle-manifest.json"
    manifest = json.loads(path.read_text())
    mutate(manifest)
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def command_selftest(args):
    with tempfile.TemporaryDirectory(prefix="trial-bundle-selftest-") as temporary:
        root = Path(temporary)
        base = root / "valid"
        synthetic_bundle(base, args.arch)
        audit_bundle(base, args.arch)
        controls = []

        def reject(name, mutate=None, replace_binary=None):
            work = root / name
            shutil.copytree(base, work)
            if mutate is not None:
                _rewrite_manifest(work, mutate)
            if replace_binary is not None:
                replace_binary(work)
            try:
                audit_bundle(work, args.arch)
            except SystemExit as exc:
                print(f"reject {name}: {exc}", flush=True)
                controls.append(name)
                return
            raise SystemExit(f"selftest {name}: audit unexpectedly passed")

        reject("incomplete-records",
               lambda manifest: manifest.__setitem__("artifacts", {}))
        reject("missing-record",
               lambda manifest: manifest["artifacts"].pop("bin/verbisage"))
        reject("unexpected-record",
               lambda manifest: manifest["artifacts"].__setitem__("bin/extra", {}))
        reject("omitted-elf-metadata",
               lambda manifest: manifest["artifacts"]["bin/verbisaged"].pop("elf_machine"))
        reject("bad-schema-version",
               lambda manifest: manifest.__setitem__("schema_version", 2))

        def wrong_arch_binary(work):
            path = work / "bin/phosh-osk-stevia"
            data = minimal_elf(ELF_MACHINE_CODES["aarch64"])
            path.write_bytes(data)

            def recompute(manifest):
                record = manifest["artifacts"]["bin/phosh-osk-stevia"]
                record["sha256"] = hashlib.sha256(data).hexdigest()
                record["size"] = len(data)
            _rewrite_manifest(work, recompute)

        reject("wrong-elf-binary", replace_binary=wrong_arch_binary)
        print(f"selftest ok: {len(controls)} negative controls rejected", flush=True)


def command_build(args):
    pins = load_pins()
    sources_root = Path(args.sources_root).resolve()
    output = Path(args.output).resolve()
    build_root = Path(args.build_root).resolve() if args.build_root else output.parent / "build"
    if output.exists():
        raise SystemExit(f"refusing to reuse existing output directory: {output}")

    verified = verify_checkouts(sources_root, pins, require_clean=not args.export_commits)
    if args.export_commits:
        order = ("keyboard_layout", "drift-type", "stevia", "verbisage", "patricia_dict")
        sources_root = export_commits(sources_root, build_root / "sources", pins, order)
    build_root.mkdir(parents=True, exist_ok=True)

    stevia = build_stevia(sources_root, build_root, args)
    verbisage = build_verbisage(sources_root, build_root, args)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / (output.name + ".staging")
    if staging.exists():
        raise SystemExit(f"staging directory already exists: {staging}")
    staging.mkdir(parents=True)
    try:
        artifacts = stage(staging, stevia, verbisage, args)
        write_manifest(staging, args, pins, verified, stevia, verbisage, artifacts)
        audit_bundle(staging, args.arch, pins)
        os.replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"bundle ready: {output}", flush=True)


def command_audit(args):
    pins = load_pins() if args.verify_pins else None
    audit_bundle(Path(args.bundle).resolve(), args.arch, pins)


def parser():
    top = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="compile and stage a new bundle")
    build.add_argument("--sources-root", required=True, type=Path,
                       help="root containing the pinned sibling checkouts")
    build.add_argument("--output", required=True, type=Path,
                       help="new bundle directory (must not exist)")
    build.add_argument("--build-root", type=Path,
                       help="directory for fresh build trees (default: <output>/../build)")
    build.add_argument("--arch", required=True, choices=ARCHES,
                       help="expected binary architecture; host: " + ", ".join(ARCHES))
    build.add_argument("--export-commits", action="store_true",
                       help="git-archive the pinned commits instead of requiring clean checkouts")
    build.add_argument("--meson-cross-file", type=Path,
                       help="optional Meson cross file for an aarch64 build")
    build.add_argument("--cargo-target", help="optional Rust target triple for the service build")
    build.add_argument("--cargo-target-dir", type=Path,
                       help="optional CARGO_TARGET_DIR (default: <build-root>/verbisage-target)")
    build.set_defaults(func=command_build)

    audit = sub.add_parser("audit", help="verify a produced bundle against its manifest")
    audit.add_argument("--bundle", required=True, type=Path)
    audit.add_argument("--arch", required=True, choices=ARCHES)
    audit.add_argument("--verify-pins", action="store_true",
                       help="also check manifest source commits against sources.json")
    audit.set_defaults(func=command_audit)

    selftest = sub.add_parser("selftest",
                              help="exercise audit rejection paths on synthetic bundles")
    selftest.add_argument("--arch", default="x86_64", choices=ARCHES)
    selftest.set_defaults(func=command_selftest)
    return top


def main():
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
