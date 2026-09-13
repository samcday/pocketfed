#!/usr/bin/env python3
"""Verify boot-critical EROFS labels against the supplied image file contexts.

Reads the EROFS with fsck.erofs's selective extractor; only temporary host files
are created. matchpathcon uses host libselinux with the supplied contexts, not
the host's policy. No filesystem is mounted and no target executable is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


BOOT_PATHS = (
    "/usr/lib/systemd/systemd",
    "/usr/bin/bash",
    "/usr/lib/systemd/systemd-journald",
    "/usr/libexec/pocketfed-liveboot-check",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_output(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{argv[0]} failed ({result.returncode}): {detail}")
    return result.stdout.strip()


def verify_root_labels(rootfs: Path, file_contexts: Path, paths=None) -> dict:
    """Return a JSON-compatible report; result=fail rejects any missing/mislabelled file."""
    rootfs = Path(rootfs).resolve(strict=True)
    file_contexts = Path(file_contexts).resolve(strict=True)
    if not rootfs.is_file() or not file_contexts.is_file():
        raise ValueError("rootfs and file_contexts must be regular files")
    paths = BOOT_PATHS if paths is None else tuple(dict.fromkeys(paths))
    if not paths or any(path not in BOOT_PATHS for path in paths):
        raise ValueError("select at least one supported boot-critical path")
    checks = []
    with tempfile.TemporaryDirectory(prefix="pocketfed-labels-") as temporary:
        scratch = Path(temporary)
        # Avoid selecting a stale adjacent file_contexts.bin or host-specific
        # local overrides: this exact text is the source used by mkfs.erofs.
        lookup_contexts = scratch / "file_contexts"
        shutil.copyfile(file_contexts, lookup_contexts)
        for index, path in enumerate(paths):
            check = {"path": path, "matches": False}
            target = scratch / f"entry-{index}"
            try:
                check["expected"] = checked_output([
                    "matchpathcon", "-N", "-n", "-m", "file", "-f", str(lookup_contexts), path,
                ])
                checked_output([
                    "fsck.erofs", f"--extract={target}", f"--path={path}",
                    "--xattrs", "--no-preserve-owner", str(rootfs),
                ])
                if not stat.S_ISREG(target.lstat().st_mode):
                    raise ValueError("boot-critical path is not a regular file")
                check["actual"] = os.getxattr(
                    target, "security.selinux", follow_symlinks=False,
                ).rstrip(b"\0").decode("ascii")
                check["matches"] = check["actual"] == check["expected"]
            except (OSError, ValueError, RuntimeError) as error:
                check["error"] = str(error)
            checks.append(check)
    return {
        "schema_version": 1,
        "result": "pass" if all(check["matches"] for check in checks) else "fail",
        "rootfs_sha256": sha256(rootfs),
        "file_contexts_sha256": sha256(file_contexts),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--file-contexts", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--path", action="append", choices=BOOT_PATHS,
                        help="repeat to select checks; defaults to all boot-critical paths")
    args = parser.parse_args()
    report = verify_root_labels(args.rootfs, args.file_contexts, args.path)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(encoded)
        temporary.replace(args.output)
    print(encoded, end="")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
