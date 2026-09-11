#!/usr/bin/python3
"""Add one verified smoo allow to a disposable fixture's SELinux policy.

This never loads policy into the host, modifies the source EROFS, or changes
enforcing/permissive state. It copies a recipe overlay and adds the patched
binary policy; a sibling JSON file records the source, result, and exact delta.
Requires the host's checkpolicy, libsepol, and Python setools packages.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ctypes as c
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

import setools


ALLOW = "(allow kernel_t device_t (io_uring (cmd)))"


class PolicyError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cil_forms(text: str) -> Counter[str]:
    """Compare whole top-level forms, preserving nested condition/constraint meaning."""
    forms: Counter[str] = Counter()
    depth = 0
    start = 0
    quoted = escaped = comment = False
    for index, char in enumerate(text):
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == ";":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "(":
            if depth == 0:
                start = index
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise PolicyError("unbalanced CIL closing parenthesis")
            if depth == 0:
                forms[text[start:index + 1]] += 1
        elif depth == 0 and not char.isspace():
            raise PolicyError("unexpected data outside a CIL form")
    if depth or quoted:
        raise PolicyError("incomplete CIL form")
    return forms


def verify_delta(before: str, after: str) -> dict:
    original, modified = cil_forms(before), cil_forms(after)
    if original[ALLOW]:
        raise PolicyError("source policy already contains the requested allow")
    removed, added = original - modified, modified - original
    if removed or added != Counter({ALLOW: 1}):
        raise PolicyError(f"policy delta is not exactly the requested allow: "
                          f"removed={list(removed.items())[:5]}, added={list(added.items())[:5]}")
    return {"removed_forms": 0, "added_forms": [ALLOW],
            "original_form_count": sum(original.values()),
            "modified_form_count": sum(modified.values())}


def to_cil(policy: Path, output: Path, mls: bool) -> str:
    command = ["checkpolicy", "-b", "-C"]
    if mls:
        command.append("-M")
    result = subprocess.run(command + ["-o", str(output), str(policy)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise PolicyError(f"checkpolicy failed: {result.stderr or result.stdout}")
    return output.read_text()


def compile_cil(source: str, version: int) -> bytes:
    lib = c.CDLL("libsepol.so.2")
    signatures = {
        "cil_db_init": [c.POINTER(c.c_void_p)],
        "cil_db_destroy": [c.POINTER(c.c_void_p)],
        "cil_add_file": [c.c_void_p, c.c_char_p, c.c_char_p, c.c_size_t],
        "cil_set_policy_version": [c.c_void_p, c.c_int],
        "cil_set_attrs_expand_generated": [c.c_void_p, c.c_int],
        "cil_set_attrs_expand_size": [c.c_void_p, c.c_uint],
        "cil_compile": [c.c_void_p],
        "cil_build_policydb": [c.c_void_p, c.POINTER(c.c_void_p)],
        "sepol_policydb_to_image": [c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(c.c_size_t)],
        "sepol_policydb_free": [c.c_void_p],
    }
    for name, args in signatures.items():
        getattr(lib, name).argtypes = args
    libc = c.CDLL(None)
    libc.free.argtypes = [c.c_void_p]
    db, policy, image, size = c.c_void_p(), c.c_void_p(), c.c_void_p(), c.c_size_t()
    lib.cil_db_init(c.byref(db))
    try:
        lib.cil_set_policy_version(db, version)
        lib.cil_set_attrs_expand_generated(db, 0)
        lib.cil_set_attrs_expand_size(db, 0)
        data = source.encode()
        if lib.cil_add_file(db, b"fixture-policy.cil", data, len(data)):
            raise PolicyError("libsepol rejected CIL source")
        if lib.cil_compile(db) or lib.cil_build_policydb(db, c.byref(policy)):
            raise PolicyError("libsepol could not compile policy")
        if lib.sepol_policydb_to_image(None, policy, c.byref(image), c.byref(size)):
            raise PolicyError("libsepol could not serialize policy")
        return c.string_at(image, size.value)
    finally:
        if image:
            libc.free(image)
        if policy:
            lib.sepol_policydb_free(policy)
        lib.cil_db_destroy(c.byref(db))


def patch_policy(original: Path, modified: Path) -> dict:
    """Patch a copied binary policy without loading it, and prove the exact delta."""
    with tempfile.TemporaryDirectory(prefix="smoo-policy-compile-") as temporary:
        directory = Path(temporary)
        source_policy = setools.SELinuxPolicy(str(original))
        before = to_cil(original, directory / "original.cil", source_policy.mls)
        if cil_forms(before)[ALLOW]:
            shutil.copyfile(original, modified)
            return {"schema_version": 1, "original_policy_sha256": sha256(original),
                    "policy_sha256": sha256(modified), "policy_version": source_policy.version,
                    "mls": source_policy.mls, "enforcing_state_changed": False,
                    "semantic_delta": {"removed_forms": 0, "added_forms": []},
                    "already_present": True, "helper_sha256": sha256(Path(__file__).resolve())}
        attributes = re.findall(r"^\(typeattribute ([^()\s]+)\)$", before, re.MULTILINE)
        preserve = "\n(expandtypeattribute (" + " ".join(attributes) + ") false)\n" if attributes else "\n"
        modified.write_bytes(compile_cil(before + preserve + ALLOW + "\n", source_policy.version))
        after_policy = setools.SELinuxPolicy(str(modified))
        if (after_policy.version, after_policy.mls) != (source_policy.version, source_policy.mls):
            raise PolicyError("policy version or MLS mode changed")
        after = to_cil(modified, directory / "modified.cil", after_policy.mls)
        delta = verify_delta(before, after)
        return {"schema_version": 1,
                "original_policy_sha256": sha256(original), "policy_sha256": sha256(modified),
                "policy_version": source_policy.version, "mls": source_policy.mls,
                "enforcing_state_changed": False, "semantic_delta": delta,
                "helper_sha256": sha256(Path(__file__).resolve())}


def prepare(rootfs: Path, overlay: Path, output: Path, policy_path: str) -> Path:
    relative = PurePosixPath(policy_path)
    if (relative.is_absolute() or any(p in ("", ".", "..") for p in policy_path.split("/"))
            or not re.fullmatch(r"etc/selinux/targeted/policy/policy\.[0-9]+", policy_path)):
        raise PolicyError("--policy-path must name etc/selinux/targeted/policy/policy.<version>")
    if not rootfs.is_file() or not overlay.is_dir():
        raise PolicyError("rootfs must exist and overlay must be a directory")
    provenance_path = output.with_name(output.name + ".policy.json")
    if output.exists() or output.is_symlink() or provenance_path.exists():
        raise PolicyError("output overlay/provenance already exists; choose a fresh output")
    with tempfile.TemporaryDirectory(prefix="smoo-policy-") as temporary:
        directory = Path(temporary)
        original, modified = directory / "original.policy", directory / "modified.policy"
        result = subprocess.run(["dump.erofs", "--cat", "--path=/" + policy_path, str(rootfs)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # dump.erofs may exit 0 on path lookup errors, so check stderr and bytes too.
        if result.returncode or result.stderr or not result.stdout:
            raise PolicyError(f"failed to extract source policy: {result.stderr.decode(errors='replace')}")
        original.write_bytes(result.stdout)
        delta_proof = patch_policy(original, modified)
        proof = {"schema_version": 1, "rootfs": str(rootfs.resolve()),
                 "rootfs_sha256": sha256(rootfs), "policy_path": policy_path,
                 "original_policy_sha256": sha256(original), "policy_sha256": sha256(modified),
                 "policy_version": delta_proof["policy_version"], "mls": delta_proof["mls"],
                 "enforcing_state_changed": False, "semantic_delta": delta_proof["semantic_delta"],
                 "helper_sha256": sha256(Path(__file__).resolve()),
                 "source_overlay": str(overlay.resolve()), "output_overlay": str(output.absolute())}
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(overlay, output, symlinks=True)
        target = output / relative
        for parent in target.parents:
            if parent == output.parent:
                break
            if parent.is_symlink():
                raise PolicyError(f"refusing output policy path through symlink: {parent}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise PolicyError("refusing to overwrite output policy symlink")
        shutil.copyfile(modified, target)
        target.chmod(0o644)
        provenance_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    return provenance_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="fresh combined generated overlay directory")
    parser.add_argument("--policy-path", default="etc/selinux/targeted/policy/policy.35")
    args = parser.parse_args()
    print(prepare(args.rootfs, args.overlay, args.output, args.policy_path))


if __name__ == "__main__":
    main()
