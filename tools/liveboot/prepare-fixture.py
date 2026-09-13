#!/usr/bin/env python3
"""Export a pinned, already-pulled PocketFed device image for local liveboot.

Only host tools run. A throwaway Podman container supplies a writable mounted
root; the ARM container is never started. Source image layers stay unchanged.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile


SCHEMA_VERSION = 1
BOOT_HEADER_SIZE = 1660


class FixtureError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in ("..", ".") for p in value.split("/")):
        raise FixtureError(f"expected a safe relative path: {value!r}")
    return path


def require_regular(path: Path, *, nonempty: bool = True) -> None:
    if path.is_symlink() or not path.is_file() or (nonempty and path.stat().st_size == 0):
        raise FixtureError(f"missing, empty, or non-regular input: {path}")


def safe_child(root: Path, relative: str) -> Path:
    result = root
    for component in relative_path(relative).parts:
        result /= component
        if result.is_symlink():
            raise FixtureError(f"refusing to traverse an image symlink: {result}")
    return result


def tree_inventory(root: Path, *, metadata: bool = False) -> dict:
    records = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        entry = {}
        if stat.S_ISLNK(info.st_mode):
            entry = {"type": "symlink", "target": os.readlink(path)}
        elif stat.S_ISDIR(info.st_mode):
            if not metadata:
                continue
            entry = {"type": "directory"}
        elif stat.S_ISREG(info.st_mode):
            entry = {"type": "file", "sha256": sha256(path), "size": info.st_size}
        else:
            raise FixtureError(f"unsupported special file: {path}")
        if metadata:
            entry["mode"] = stat.S_IMODE(info.st_mode)
            entry["mtime_ns"] = info.st_mtime_ns
        records[path.relative_to(root).as_posix()] = entry
    return records


def image_identity(reference: str) -> dict:
    pinned = re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", reference)
    local_id = re.fullmatch(r"sha256:[0-9a-f]{64}", reference)
    if not pinned and not local_id:
        raise FixtureError("--image must be pinned with @sha256:<digest> or a full local sha256:<image-id>; resolve local tags with podman image inspect --format '{{.Id}}'")
    inspected = json.loads(run(["podman", "image", "inspect", reference], capture=True))
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise FixtureError("podman did not identify exactly one local image")
    info = inspected[0]
    digest = reference.rsplit("@", 1)[-1]
    if pinned and info.get("Digest") != digest and reference not in info.get("RepoDigests", []):
        raise FixtureError("local image digest does not match the requested reference")
    image_id = info.get("Id", "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", image_id):
        raise FixtureError("podman returned an invalid image ID")
    if local_id and reference != "sha256:" + image_id:
        raise FixtureError("local image ID does not match the requested identity")
    if info.get("Architecture") != "arm64" or info.get("Os") != "linux":
        raise FixtureError("the device image must be linux/arm64")
    return {"reference": reference, "id": "sha256:" + image_id, "digest": info.get("Digest"),
            "repo_digests": sorted(info.get("RepoDigests", [])), "architecture": info["Architecture"],
            "os": info["Os"], "created": info.get("Created")}


def extract_shim(aboot: Path, compressed: Path, raw: Path) -> None:
    """Accept the same strict Android v2 layout as PocketFed's finalizer."""
    require_regular(aboot)
    total_size = aboot.stat().st_size
    with aboot.open("rb") as stream:
        header = stream.read(BOOT_HEADER_SIZE)
        if len(header) != BOOT_HEADER_SIZE or header[:8] != b"ANDROID!":
            raise FixtureError("aboot.img is not an Android v2 boot image")
        u32 = lambda offset: struct.unpack_from("<I", header, offset)[0]
        page, version = u32(36), u32(40)
        if version != 2 or u32(1644) != BOOT_HEADER_SIZE:
            raise FixtureError("unsupported Android boot header version or size")
        if page < BOOT_HEADER_SIZE or page & (page - 1):
            raise FixtureError("invalid Android boot image page size")
        kernel, ramdisk, second, recovery, dtb = (u32(o) for o in (8, 16, 24, 1632, 1648))
        if not kernel or not ramdisk or not dtb:
            raise FixtureError("Android boot kernel, ramdisk, and DTB must be nonempty")
        align = lambda size: (size + page - 1) & -page
        recovery_offset = page + align(kernel) + align(ramdisk) + align(second)
        expected = recovery_offset + align(recovery) + align(dtb)
        if total_size != expected:
            raise FixtureError("Android boot payloads are truncated or contain trailing data")
        if recovery and struct.unpack_from("<Q", header, 1636)[0] != recovery_offset:
            raise FixtureError("Android boot recovery DTBO offset is inconsistent")
        stream.seek(page)
        data = stream.read(kernel)
    try:
        unpacked = gzip.decompress(data)
    except (OSError, EOFError) as error:
        raise FixtureError("Android kernel section is not a valid gzip ABLX shim") from error
    if not unpacked:
        raise FixtureError("Android kernel section contains an empty ABLX shim")
    compressed.write_bytes(data)
    raw.write_bytes(unpacked)


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


def extract_kernel(root: Path, output: Path, dtb_relative: str) -> dict:
    module_base = safe_child(root, "usr/lib/modules")
    releases = list(module_base.iterdir()) if module_base.is_dir() else []
    if len(releases) != 1 or releases[0].is_symlink() or not releases[0].is_dir():
        raise FixtureError("image must contain exactly one regular /usr/lib/modules/<release> directory")
    source = releases[0]
    release = source.name
    if not re.fullmatch(r"[A-Za-z0-9_.+~-]+", release):
        raise FixtureError(f"unsafe kernel release: {release!r}")
    dtb = safe_child(source, "dtb/" + str(relative_path(dtb_relative)))
    kernel, config, aboot = (safe_child(source, name) for name in ("vmlinuz", "config", "aboot.img"))
    for path in (dtb, kernel, config, aboot):
        require_regular(path)
    bundle = output / "kernel-bundle"
    bundle.mkdir()
    modules = bundle / "modules"
    destination = modules / "lib/modules" / release
    destination.mkdir(parents=True)
    omitted = []
    # Kernel packages include source/build links into an unavailable build host.
    # Every other symlink or special node is rejected, never followed.
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            if relative.as_posix() in ("source", "build"):
                omitted.append(relative.as_posix())
                continue
            raise FixtureError(f"unexpected symlink in kernel module tree: {path}")
        if path.is_dir():
            target.mkdir(exist_ok=True)
        elif path.is_file():
            shutil.copyfile(path, target)
            target.chmod(stat.S_IMODE(path.stat().st_mode))
        else:
            raise FixtureError(f"unexpected special file in kernel module tree: {path}")
    image = bundle / "Image.gz"
    raw_kernel = canonical_kernel(kernel.read_bytes())
    image.write_bytes(gzip.compress(raw_kernel, mtime=0))
    bundle_dtb = bundle / "dtb" / dtb_relative
    bundle_dtb.parent.mkdir(parents=True)
    shutil.copyfile(dtb, bundle_dtb)
    shutil.copyfile(config, bundle / "kernel.config")
    extract_shim(aboot, output / "production-ablx-shim.gz", output / "production-ablx-shim.bin")
    records = tree_inventory(modules)
    manifest = {"schema_version": 1, "release": release,
                "image": {"path": "Image.gz", "sha256": sha256(image)},
                "dtb": {"path": bundle_dtb.relative_to(bundle).as_posix(), "sha256": sha256(bundle_dtb)},
                "modules_install": "modules",
                "module_files": {path: record["sha256"] for path, record in records.items()}}
    (bundle / "bundle.json").write_bytes(encoded(manifest))
    return {"release": release, "source_vmlinuz_sha256": sha256(kernel),
            "source_aboot_sha256": sha256(aboot), "config_sha256": sha256(config),
            "omitted_module_symlinks": omitted, "module_file_count": len(records)}


def apply_overlay(root: Path, overlay: Path) -> None:
    """Install supplied policy with root ownership without following target links."""
    for path in sorted(overlay.rglob("*")):
        relative = path.relative_to(overlay).as_posix()
        parent_relative = str(PurePosixPath(relative).parent)
        parent = root if parent_relative == "." else safe_child(root, parent_relative)
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / path.name
        if path.is_dir() and not path.is_symlink():
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                raise FixtureError(f"overlay directory conflicts with image path: {target}")
            target.mkdir(exist_ok=True)
            target.chmod(stat.S_IMODE(path.stat().st_mode))
            os.chown(target, 0, 0)
        elif path.is_symlink() or path.is_file():
            if target.is_dir() and not target.is_symlink():
                raise FixtureError(f"overlay leaf conflicts with image directory: {target}")
            if target.exists() or target.is_symlink():
                target.unlink()
            if path.is_symlink():
                target.symlink_to(os.readlink(path))
                os.chown(target, 0, 0, follow_symlinks=False)
            else:
                shutil.copyfile(path, target)
                target.chmod(stat.S_IMODE(path.stat().st_mode))
                os.chown(target, 0, 0)
        else:
            raise FixtureError(f"overlay contains a special file: {path}")


def resolve_image_path(root: Path, relative: Path) -> Path:
    """Resolve symlinks in the image namespace, never against the host's /."""
    pending = list(relative.parts)
    resolved = []
    followed = 0
    while pending:
        component = pending.pop(0)
        if component in ("", ".", "/"):
            continue
        if component == "..":
            if resolved:
                resolved.pop()
            continue
        path = root.joinpath(*resolved, component)
        if path.is_symlink():
            followed += 1
            if followed > 40:
                raise FixtureError(f"too many image symlink traversals: {relative}")
            target = Path(os.readlink(path))
            if target.is_absolute():
                resolved = []
            pending = list(target.parts) + pending
        else:
            resolved.append(component)
    return Path(*resolved)


def flatten_root(root: Path) -> dict:
    """Remove unused OSTree objects before pathname-based SELinux labeling.

    Device OCI roots contain /usr files hardlinked to /sysroot/ostree/repo.
    EROFS shares their inode and takes the first encountered pathname's label.
    Keeping those object paths therefore labels systemd/default executables as
    default_t. This liveboot mounts an already-materialized flat root, so retain
    /sysroot and /ostree scaffolding but remove the unused repository copies.
    """
    for name in ("usr", "etc", "var"):
        path = safe_child(root, name)
        if not path.is_dir():
            raise FixtureError(f"flat userspace requires a materialized /{name} directory")
    repository = safe_child(root, "sysroot/ostree/repo")
    if not repository.exists():
        return {"mode": "flat-root", "removed_paths": [], "checked_runtime_symlinks": 0}
    if not repository.is_dir():
        raise FixtureError("unexpected non-directory OSTree repository")
    checked = 0
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        names[:] = [name for name in names if parent / name != repository]
        for name in names + files:
            path = parent / name
            if not path.is_symlink():
                continue
            checked += 1
            relative = path.relative_to(root)
            target = resolve_image_path(root, relative)
            if target.parts[:3] == ("sysroot", "ostree", "repo"):
                raise FixtureError(f"runtime symlink depends on the OSTree repository: /{relative} -> /{target}")
    shutil.rmtree(repository)
    return {"mode": "flat-root", "removed_paths": ["sysroot/ostree/repo"],
            "checked_runtime_symlinks": checked}


def required_label_paths(root: Path) -> list[str]:
    paths = ["/usr/lib/systemd/systemd", "/usr/bin/bash", "/usr/lib/systemd/systemd-journald"]
    reporter = "usr/libexec/pocketfed-liveboot-check"
    if safe_child(root, reporter).exists():
        paths.append("/" + reporter)
    return paths


def verify_reuse(output: Path, fingerprint: str) -> dict:
    require_regular(output / "fixture.json")
    manifest = json.loads((output / "fixture.json").read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("input_fingerprint") != fingerprint:
        raise FixtureError("existing fixture does not match these exact inputs and exporter version")
    current = tree_inventory(output)
    current.pop("fixture.json", None)
    if current != manifest.get("artifacts"):
        raise FixtureError("existing fixture artifacts changed, are missing, or contain unexpected files")
    return manifest


def worker(context_path: Path) -> None:
    context = json.loads(context_path.read_text())
    output = Path(context["temporary_output"])
    root = Path(run(["podman", "mount", context["container_id"]], capture=True))
    try:
        metadata = extract_kernel(root, output, context["inputs"]["dtb"])
        # All modules are supplied by kboop's separately versioned modules image.
        shutil.rmtree(safe_child(root, "usr/lib/modules"))
        safe_child(root, "usr/lib/modules").mkdir(mode=0o755)
        if context.get("overlay"):
            overlay = Path(context["overlay"])
            if tree_inventory(overlay, metadata=True) != context["inputs"]["overlay"]:
                raise FixtureError("overlay changed after input fingerprinting")
            apply_overlay(root, overlay)
        if context["inputs"].get("smoo_policy"):
            helper = Path(__file__).with_name("prepare-smoo-policy.py")
            spec = importlib.util.spec_from_file_location("smoo_policy", helper)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            policies = sorted(safe_child(root, "etc/selinux/targeted/policy").glob("policy.*"))
            policies = [p for p in policies if re.fullmatch(r"policy\.[0-9]+", p.name)]
            if len(policies) != 1:
                raise FixtureError("expected one active binary SELinux policy for smoo overlay")
            original = policies[0]
            require_regular(original)
            patched = output / "patched-policy"
            proof = module.patch_policy(original, patched)
            shutil.copyfile(patched, original)
            patched.unlink()
            proof["policy_path"] = original.relative_to(root).as_posix()
            (output / "smoo-policy.json").write_bytes(encoded(proof))
        metadata["root_layout"] = flatten_root(root)
        policy = safe_child(root, "etc/selinux/targeted/contexts/files/file_contexts")
        require_regular(policy)
        erofs_args = ["mkfs.erofs", "--quiet", "-zlz4hc", "--file-contexts=" + str(policy),
                      str(output / "rootfs.erofs"), str(root)]
        run(erofs_args)
        # --extract without a destination verifies decoding of every data extent.
        run(["fsck.erofs", "--extract", str(output / "rootfs.erofs")])
        label_command = [shutil.which("python3"), str(Path(__file__).with_name("verify-root-labels.py")),
                         "--rootfs", str(output / "rootfs.erofs"), "--file-contexts", str(policy),
                         "--output", str(output / "root-labels.json")]
        for path in required_label_paths(root):
            label_command += ["--path", path]
        run(label_command)
        metadata["selinux_file_contexts_sha256"] = sha256(policy)
        metadata["erofs_version"] = run(["mkfs.erofs", "-V"], capture=True)
        artifacts = tree_inventory(output)
        manifest = {"schema_version": SCHEMA_VERSION, "input_fingerprint": context["input_fingerprint"],
                    "inputs": context["inputs"], "kernel": metadata, "artifacts": artifacts,
                    "rootfs": "rootfs.erofs", "kernel_bundle": "kernel-bundle/bundle.json",
                    "abl_exorcist": "production-ablx-shim.bin", "status": "prepared-not-booted"}
        (output / "fixture.json").write_bytes(encoded(manifest))
    finally:
        run(["podman", "unmount", context["container_id"]], capture=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already-local device OCI reference pinned by sha256 digest")
    parser.add_argument("--output", required=True, type=Path, help="fresh output directory")
    parser.add_argument("--dtb", required=True, help="DTB path under the kernel's dtb/ directory, e.g. qcom/sdm670-google-sargo.dtb")
    parser.add_argument("--overlay", type=Path, help="explicit userspace additions/replacements; included in input fingerprint")
    parser.add_argument("--smoo-policy", action="store_true", help="add the verified enforcing USB-storage permission in the disposable root")
    parser.add_argument("--reuse", action="store_true", help="reuse only if inputs and every output artifact verify exactly")
    args = parser.parse_args()
    dtb = str(relative_path(args.dtb))
    image = image_identity(args.image)
    overlay = args.overlay.resolve() if args.overlay else None
    if overlay is not None and not overlay.is_dir():
        raise FixtureError("--overlay must be a directory")
    inputs = {"image": image, "dtb": dtb, "overlay": tree_inventory(overlay, metadata=True) if overlay else None,
              "exporter_sha256": sha256(Path(__file__).resolve()),
              "label_verifier_sha256": sha256(Path(__file__).with_name("verify-root-labels.py")),
              "smoo_policy": args.smoo_policy,
              "policy_helper_sha256": sha256(Path(__file__).with_name("prepare-smoo-policy.py")) if args.smoo_policy else None}
    fingerprint = hashlib.sha256(encoded(inputs)).hexdigest()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        if not args.reuse:
            raise FixtureError("output exists; choose a fresh path or pass --reuse for strict verification")
        verify_reuse(output, fingerprint)
        print(output / "fixture.json")
        return
    for command in ("podman", "mkfs.erofs", "fsck.erofs"):
        if shutil.which(command) is None:
            raise FixtureError(f"required host command is missing: {command}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + output.name + ".", dir=output.parent))
    context_path = temporary.parent / (temporary.name + ".json")
    container_id = None
    try:
        container_id = run(["podman", "create", "--pull=never", "--network=none", "--entrypoint=/bin/false", image["id"]], capture=True)
        if not re.fullmatch(r"[0-9a-f]{64}", container_id):
            raise FixtureError("podman create returned an invalid container ID")
        context = {"temporary_output": str(temporary), "container_id": container_id,
                   "inputs": inputs, "input_fingerprint": fingerprint, "overlay": str(overlay) if overlay else None}
        context_path.write_bytes(encoded(context))
        # Some desktop launchers interpose /proc/self/exe, making sys.executable
        # point at the GUI AppImage. Resolve the actual host interpreter on PATH.
        interpreter = sys.executable
        if not Path(interpreter).name.startswith("python"):
            interpreter = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else shutil.which("python3")
        if not interpreter:
            raise FixtureError("required host command is missing: python3")
        run(["podman", "unshare", interpreter, str(Path(__file__).resolve()), "--_worker", str(context_path)])
        verify_reuse(temporary, fingerprint)
        temporary.rename(output)
        print(output / "fixture.json")
    finally:
        if container_id:
            run(["podman", "rm", container_id], capture=True)
        context_path.unlink(missing_ok=True)
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--_worker":
            worker(Path(sys.argv[2]))
        else:
            main()
    except (FixtureError, OSError, EOFError, ValueError, subprocess.CalledProcessError) as error:
        print(f"prepare-fixture: {error}", file=sys.stderr)
        sys.exit(1)
