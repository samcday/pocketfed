#!/usr/bin/env python3
"""Seal a kboop version-1 candidate bundle from already-downloaded Fedora RPMs.

Nothing is installed on the host: the kernel and modules are unpacked into a new
candidate directory, depmod runs against the bundle's own System.map, and the
finished bundle is validated with the same checks build-kernel.py applies. The
kernel/DTB/depmod/module helpers are imported from tools/liveboot rather than
copied. Fedora ships an EFI zboot vmlinuz; prepare-fixture.py already decodes it.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import importlib.util
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import sys
import tempfile


LIVEBOOT = Path(__file__).resolve().parents[2] / "tools" / "liveboot"
REPO = Path(__file__).resolve().parents[2]
COMPONENTS = (
    "kernel-core",
    "kernel-modules-core",
    "kernel-modules",
    "kernel-modules-extra",
    "kernel-modules-internal",
)
OPTIONAL_COMPONENTS = ("kernel-devel",)
EARLY_MODULE_CONFIG = "tools/liveboot/profiles/google-sargo-initrd.conf"


class BundleError(Exception):
    pass


def load_helper(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LIVEBOOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_kernel = load_helper("build_kernel", "build-kernel.py")
prepare_fixture = load_helper("prepare_fixture", "prepare-fixture.py")
liveboot_run = load_helper("liveboot_run", "run.py")


def parse_rpm_filename(path: Path) -> dict:
    """Fallback metadata derived only from the RPM file name (no epoch)."""
    stem = path.name[:-4] if path.name.endswith(".rpm") else path.name
    stem, _, arch = stem.rpartition(".")
    name, version, release = stem.rsplit("-", 2)
    return {"name": name, "epoch": None, "version": version, "release": release,
            "arch": arch, "sourcerpm": f"{name}-{version}-{release}.src.rpm"}


def rpm_metadata(path: Path) -> dict:
    rpm = shutil.which("rpm")
    if rpm:
        query = "--qf=%{NAME}\t%{EPOCH}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{SOURCERPM}"
        output = subprocess.run([rpm, "-qp", query, str(path)], check=True, text=True,
                                stdout=subprocess.PIPE).stdout
        name, epoch, version, release, arch, sourcerpm = output.split("\t")
        if epoch in ("", "(none)"):
            epoch = None
    else:
        fallback = parse_rpm_filename(path)
        name, epoch, version, release, arch, sourcerpm = (
            fallback["name"], fallback["epoch"], fallback["version"],
            fallback["release"], fallback["arch"], fallback["sourcerpm"])
    nevra = (f"{name}-{epoch}:{version}-{release}.{arch}" if epoch not in (None, "0")
             else f"{name}-{version}-{release}.{arch}")
    return {"basename": path.name, "name": name, "epoch": epoch, "version": version,
            "release": release, "arch": arch, "sourcerpm": sourcerpm, "nevra": nevra,
            "sha256": build_kernel.sha256(path)}


def discover_rpms(rpm_dir: Path) -> tuple[dict[str, Path], str, str, list[dict]]:
    if not rpm_dir.is_dir():
        raise BundleError(f"RPM directory does not exist: {rpm_dir}")
    paths = sorted(p for p in rpm_dir.iterdir() if p.is_file() and p.suffix == ".rpm")
    if not paths:
        raise BundleError(f"no RPMs found in {rpm_dir}")
    records = [rpm_metadata(path) for path in paths]
    by_name: dict[str, Path] = {}
    for path, record in zip(paths, records):
        if record["name"] in by_name:
            raise BundleError(f"duplicate input package: {record['name']}")
        by_name[record["name"]] = path
    missing = [name for name in COMPONENTS if name not in by_name]
    if missing:
        raise BundleError("missing required kernel RPMs: " + ", ".join(missing))
    used = [record for record in records if record["name"] in COMPONENTS + OPTIONAL_COMPONENTS]
    variants = {(record["version"], record["release"], record["arch"]) for record in used}
    if len(variants) != 1:
        raise BundleError("input kernel RPMs do not share one version-release.arch")
    version, rpm_release, arch = variants.pop()
    if arch != "aarch64":
        raise BundleError(f"kernel RPM architecture must be aarch64, not {arch!r}")
    release = f"{version}-{rpm_release}.{arch}"
    sources = {record["sourcerpm"] for record in used if record["sourcerpm"]}
    if len(sources) != 1:
        raise BundleError("input kernel RPMs do not share one source package")
    sourcerpm = sources.pop()
    if not sourcerpm.endswith(".src.rpm"):
        raise BundleError(f"unexpected source RPM name: {sourcerpm!r}")
    return (by_name, release, sourcerpm[:-len(".src.rpm")], records)


def extract_rpm(rpm: Path, destination: Path, patterns: list[str] | None = None) -> None:
    rpm2cpio = shutil.which("rpm2cpio")
    cpio = shutil.which("cpio")
    if not rpm2cpio or not cpio:
        raise BundleError("host rpm2cpio and cpio are required to unpack the RPMs")
    destination.mkdir(parents=True, exist_ok=True)
    producer = subprocess.Popen([rpm2cpio, str(rpm)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    argv = [cpio, "-idm", "--quiet", "--no-absolute-filenames"]
    if patterns:
        argv += patterns
    try:
        consumer = subprocess.Popen(argv, stdin=producer.stdout, cwd=destination,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        producer.stdout.close()
        _, consumer_error = consumer.communicate()
        producer_error = producer.stderr.read()
    finally:
        producer.stderr.close()
        if producer.poll() is None:
            producer.terminate()
        producer.wait()
    if producer.returncode or consumer.returncode:
        detail = (producer_error + consumer_error).decode(errors="replace").strip()
        raise BundleError(f"failed to unpack {rpm.name}: {detail}")


def merge_into(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            raise BundleError(f"unexpected symlink in module tree: {path}")
        if path.is_dir():
            if target.exists() and not target.is_dir():
                raise BundleError(f"module directory conflicts with a file: {target}")
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            if target.exists() or target.is_symlink():
                raise BundleError(f"internal module collides with an installed module: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        else:
            raise BundleError(f"unexpected special file in module tree: {path}")


def relocate_internal(release_root: Path) -> None:
    """Match the installed modules.order, which records internal tests under kernel/."""
    internal = release_root / "internal"
    if not internal.exists():
        return
    if internal.is_symlink() or not internal.is_dir():
        raise BundleError(f"unexpected internal module path: {internal}")
    merge_into(internal, release_root / "kernel")
    leftover = [path for path in internal.rglob("*") if not path.is_dir() or path.is_symlink()]
    if leftover:
        raise BundleError(f"internal module relocation left files behind: {leftover[0]}")
    shutil.rmtree(internal)


def strip_kernel_artifacts(release_root: Path) -> None:
    for name in ("vmlinuz", ".vmlinuz.hmac", "config", "System.map", "symvers.xz"):
        target = release_root / name
        if target.is_symlink():
            target.unlink()
        elif target.is_file():
            target.unlink()
        elif target.exists():
            raise BundleError(f"unexpected kernel artifact in module tree: {target}")
    for name in ("build", "source"):
        target = release_root / name
        if target.is_symlink():
            target.unlink()
    dtb = release_root / "dtb"
    if dtb.is_symlink():
        raise BundleError(f"unexpected symlink in module tree: {dtb}")
    if dtb.is_dir():
        shutil.rmtree(dtb)
    elif dtb.exists():
        raise BundleError(f"unexpected device-tree path in module tree: {dtb}")


def synthesize_modules_order(source: Path, destination: Path) -> int:
    """Translate the installed modules.order into a build-tree-shaped list.

    Fedora records installed module paths (kernel/.../name.ko). build-kernel.py
    expects source-relative .o entries and re-adds the kernel/ install prefix
    when it compares against the installed tree.
    """
    entries = []
    seen = set()
    for raw in source.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        value = posixpath.normpath(line)
        if not value.startswith("kernel/") or not value.endswith(".ko"):
            raise BundleError(f"unexpected modules.order entry: {raw!r}")
        entry = value[len("kernel/"):-len(".ko")] + ".o"
        if entry in seen:
            raise BundleError(f"duplicate modules.order entry: {entry}")
        seen.add(entry)
        entries.append(entry)
    if not entries:
        raise BundleError("modules.order is empty")
    destination.write_text("\n".join(sorted(entries)) + "\n")
    return len(entries)


def module_name(path: str) -> str:
    base = posixpath.basename(path)
    return base.split(".ko")[0].replace("-", "_")


def installed_module_names(dep: Path) -> set[str]:
    names = set()
    for line in dep.read_text().splitlines():
        field = line.partition(":")[0].strip()
        if field:
            names.add(module_name(field))
    return names


def builtin_module_names(builtin: Path) -> set[str]:
    names = set()
    for line in builtin.read_text().splitlines():
        line = line.strip()
        if line:
            names.add(module_name(line))
    return names


def classify_early_modules(names: list[str], installed: set[str], builtin: set[str]) -> list[tuple[str, str]]:
    result = []
    for name in names:
        key = name.replace("-", "_")
        if key in installed:
            status = "present"
        elif key in builtin:
            status = "builtin"
        else:
            status = "absent"
        result.append((name, status))
    return result


def early_module_report(release_root: Path, config: Path) -> list[tuple[str, str]]:
    names = liveboot_run.early_modules(
        {"dracut_config": config.resolve().relative_to(REPO).as_posix()}, REPO)
    installed = installed_module_names(release_root / "modules.dep")
    builtin = builtin_module_names(release_root / "modules.builtin")
    return classify_early_modules(names, installed, builtin)


def encode_image_gz(vmlinuz: bytes) -> bytes:
    """Decode Fedora's EFI zboot vmlinuz with prepare-fixture.py, then re-gzip it."""
    raw = prepare_fixture.canonical_kernel(vmlinuz)
    return gzip.compress(raw, mtime=0)


def bundle_manifest(release: str, output: Path, dtb_bundle: str, module_files: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "release": release,
        "image": {"path": "Image.gz", "sha256": build_kernel.sha256(output / "Image.gz")},
        "dtb": {"path": dtb_bundle, "sha256": build_kernel.sha256(output / dtb_bundle)},
        "modules_install": "modules",
        "module_files": module_files,
    }


def verify_bundle(output: Path, release: str, dtb: str, install: Path,
                  commands) -> dict[str, str]:
    """Reuse build-kernel.py's finished-bundle validation on a Kbuild-shaped view."""
    staging = output / ".verify"
    try:
        dts = staging / "arch" / "arm64" / "boot" / "dts" / dtb
        dts.parent.mkdir(parents=True)
        generated = staging / "include" / "generated"
        generated.mkdir(parents=True)
        os.link(output / "Image.gz", staging / "arch" / "arm64" / "boot" / "Image.gz")
        os.link(output / "dtb" / dtb, dts)
        os.link(output / "kernel.config", staging / ".config")
        os.link(output / "System.map", staging / "System.map")
        generated.joinpath("utsrelease.h").write_text(f'#define UTS_RELEASE "{release}"\n')
        release_root = install / "lib" / "modules" / release
        order = staging / "modules.order"
        synthesize_modules_order(release_root / "modules.order", order)
        build_kernel.verify_kernel(staging, dtb, release)
        return build_kernel.verify_modules(install, release, order, commands, "modinfo")
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def produce(args: argparse.Namespace) -> Path:
    rpm_dir = args.rpm_dir.resolve()
    output = args.output.absolute()
    dtb = build_kernel.relative(args.dtb).as_posix()
    if not dtb.endswith(".dtb"):
        raise BundleError("--dtb must be a path below the kernel dtb directory ending in .dtb")
    rpms, release, koji_nvr, records = discover_rpms(rpm_dir)
    if output.exists() or output.is_symlink():
        raise BundleError(f"candidate already exists; choose a fresh --output: {output}")
    output.mkdir(parents=True)
    provenance = {
        "schema_version": 1,
        "producer": "pocketfed-hwe/hwe/tools/fedora-kernel-bundle.py",
        "producer_sha256": build_kernel.sha256(Path(__file__).resolve()),
        "release": release,
        "koji_build_nvr": koji_nvr,
        "source": "fedora-koji-rpms",
        "rpm_dir": str(rpm_dir),
        "rpms": records,
    }
    work = None
    try:
        commands = build_kernel.Commands(output / "build.log", build_kernel.build_environment())
        work = Path(tempfile.mkdtemp(prefix=".work-", dir=output))
        for component in COMPONENTS:
            if component == "kernel-core":
                release_prefix = f"./lib/modules/{release}"
                patterns = [f"{release_prefix}/{name}" for name in
                            ("vmlinuz", "config", "System.map", "modules.builtin", "modules.builtin.modinfo")]
                patterns.append(f"{release_prefix}/dtb/{dtb}")
                extract_rpm(rpms[component], work, patterns)
            else:
                extract_rpm(rpms[component], work)
        modules_base = work / "lib" / "modules"
        releases = sorted(p.name for p in modules_base.iterdir()) if modules_base.is_dir() else []
        if releases != [release]:
            raise BundleError(f"RPM module tree must contain exactly {release!r}, found {releases!r}")
        extracted = modules_base / release
        upstream = extracted / "vmlinuz"
        build_kernel.regular(upstream)
        gzip_image = output / "Image.gz"
        gzip_image.write_bytes(encode_image_gz(upstream.read_bytes()))
        build_kernel.regular(extracted / "config")
        build_kernel.regular(extracted / "System.map")
        build_kernel.regular(extracted / "dtb" / dtb)
        shutil.copyfile(extracted / "config", output / "kernel.config")
        shutil.copyfile(extracted / "System.map", output / "System.map")
        (output / "dtb" / Path(dtb).parent).mkdir(parents=True)
        shutil.copyfile(extracted / "dtb" / dtb, output / "dtb" / dtb)
        install = output / "modules"
        destination = install / "lib" / "modules" / release
        destination.parent.mkdir(parents=True)
        shutil.move(str(extracted), str(destination))
        strip_kernel_artifacts(destination)
        relocate_internal(destination)
        log_start = (output / "build.log").stat().st_size if (output / "build.log").exists() else 0
        commands.run([args.depmod, "-a", "-e", "-F", str(output / "System.map"),
                      "-b", str(install), release])
        with (output / "build.log").open("rb") as log:
            log.seek(log_start)
            diagnostics = log.read().decode(errors="replace")
        if "needs unknown symbol" in diagnostics or "ERROR:" in diagnostics:
            raise BundleError("depmod reported unresolved symbols or an error; see build.log")
        module_files = verify_bundle(output, release, dtb, install, commands)
        manifest = bundle_manifest(release, output, f"dtb/{dtb}", module_files)
        build_kernel.write_json(output / "bundle.json", manifest)
        report = early_module_report(destination, REPO / EARLY_MODULE_CONFIG)
        (output / "early-modules.txt").write_text(
            "".join(f"{name} {status}\n" for name, status in report))
        counts = {status: sum(1 for _, value in report if value == status)
                  for status in ("present", "builtin", "absent")}
        print(f"early-modules: {counts['present']} present, {counts['builtin']} builtin, "
              f"{counts['absent']} absent ({len(report)} total)", flush=True)
        provenance["module_count"] = len(module_files)
        provenance["artifacts"] = {name: build_kernel.sha256(output / name) for name in
                                   ("bundle.json", "Image.gz", "kernel.config", "System.map",
                                    "early-modules.txt", "build.log")}
        provenance["completed_at"] = datetime.now(timezone.utc).isoformat()
        build_kernel.write_json(output / "provenance.json", provenance)
    except (BundleError, build_kernel.BuildError, prepare_fixture.FixtureError,
            OSError, ValueError, subprocess.CalledProcessError) as error:
        provenance["error"] = str(error)
        build_kernel.write_json(output / "failure.json", provenance)
        raise
    finally:
        if work is not None and work.exists():
            shutil.rmtree(work)
    return output / "bundle.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpm-dir", type=Path, required=True,
                        help="directory of already-downloaded aarch64 kernel RPMs")
    parser.add_argument("--output", type=Path, required=True,
                        help="new, immutable candidate directory")
    parser.add_argument("--dtb", required=True,
                        help="e.g. qcom/sdm670-google-sargo.dtb (below the release dtb/ directory)")
    parser.add_argument("--depmod", default="depmod")
    args = parser.parse_args()
    try:
        print(produce(args))
    except (BundleError, build_kernel.BuildError, prepare_fixture.FixtureError,
            OSError, subprocess.CalledProcessError) as error:
        print(f"fedora-kernel-bundle: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
