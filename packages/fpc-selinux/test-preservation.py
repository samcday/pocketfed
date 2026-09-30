#!/usr/bin/python3
"""Require exact preservation of decompiled policy outside the reviewed additions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ATTR_ADDITIONS = {
    "device_node": {"pocketfed_fpc_device_t", "pocketfed_fpc_tee_device_t"},
    "file_type": {"pocketfed_fpc_auth_state_t", "pocketfed_fpc_auth_run_t"},
    "non_auth_file_type": {"pocketfed_fpc_auth_state_t", "pocketfed_fpc_auth_run_t"},
    "non_security_file_type": {"pocketfed_fpc_auth_state_t", "pocketfed_fpc_auth_run_t"},
    "pidfile": {"pocketfed_fpc_auth_run_t"},
}
TYPES = ATTR_ADDITIONS["device_node"] | ATTR_ADDITIONS["file_type"]
# Canonical checkpolicy output. Generic distribution file_type rules account
# for filesystem associate; its existing directory search makes that explicit
# module grant redundant after optimization. The access-query test covers it.
NEW_FORMS = {
    "(allow fprintd_t pocketfed_fpc_auth_run_t (sock_file (write getattr)))",
    "(allow fprintd_t pocketfed_fpc_device_t (chr_file (ioctl read write getattr open)))",
    "(allow fprintd_t pocketfed_fpc_tee_device_t (chr_file (ioctl read write getattr open)))",
    "(allow init_t pocketfed_fpc_auth_state_t (dir (create setattr)))",
    "(allow pocketfed_fpc_auth_run_t self (filesystem (associate)))",
    "(allow pocketfed_fpc_auth_state_t self (filesystem (associate)))",
    "(allowx fprintd_t pocketfed_fpc_device_t (ioctl chr_file (((range 0x4600 0x4602)))))",
    "(allowx fprintd_t pocketfed_fpc_tee_device_t (ioctl chr_file (((range 0xa400 0xa403) 0xa405))))",
} | {f"(type {t})" for t in TYPES} | {f"(roletype object_r {t})" for t in TYPES}
NEW_CONTEXTS = {
    "/dev/fpc1020\t-c\tsystem_u:object_r:pocketfed_fpc_device_t:s0",
    "/dev/tee([0-9]|1[0-5])\t-c\tsystem_u:object_r:pocketfed_fpc_tee_device_t:s0",
    "/run/pocketfed-fpc-auth\t-d\tsystem_u:object_r:pocketfed_fpc_auth_run_t:s0",
    "/run/pocketfed-fpc-auth/token\\.sock\t-s\tsystem_u:object_r:pocketfed_fpc_auth_run_t:s0",
    "/var/lib/pocketfed-fpc-auth(/.*)?\tsystem_u:object_r:pocketfed_fpc_auth_state_t:s0",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decompile(path):
    with tempfile.TemporaryDirectory(prefix="fpc-preservation-") as tmp:
        output = Path(tmp) / "policy.cil"
        subprocess.run(["checkpolicy", "-M", "-b", "-C", "-o", str(output), str(path)],
                       check=True, capture_output=True)
        return output.read_text()


def remove_exact_additions(lines, additions):
    for form in additions:
        assert lines.count(form + "\n") == 1, ("missing or repeated addition", form)
    return [line for line in lines if line.removesuffix("\n") not in additions]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-policy", type=Path, required=True)
    parser.add_argument("--candidate-policy", type=Path, required=True)
    parser.add_argument("--base-contexts", type=Path, required=True, help="contexts/files directory")
    parser.add_argument("--candidate-contexts", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    before, after = decompile(args.base_policy), decompile(args.candidate_policy)
    base_lines = before.splitlines(keepends=True)
    lines = remove_exact_additions(after.splitlines(keepends=True), NEW_FORMS)
    for name, additions in ATTR_ADDITIONS.items():
        prefix = f"(typeattributeset {name} "
        old = [line for line in base_lines if line.startswith(prefix)]
        new = [line for line in lines if line.startswith(prefix)]
        assert len(old) == len(new) == 1, name
        pattern = rf"\(typeattributeset {re.escape(name)} \(([A-Za-z0-9_ ]*)\)\)\n"
        old_match, new_match = re.fullmatch(pattern, old[0]), re.fullmatch(pattern, new[0])
        assert old_match and new_match, name
        old_types, new_types = set(old_match[1].split()), set(new_match[1].split())
        assert new_types == old_types | additions and not old_types & additions, name
        lines[lines.index(new[0])] = old[0]
    # Compare the complete remaining byte sequence, including conditional
    # nesting and rule order, rather than treating all policy lines as a set.
    assert "".join(lines) == before, "unreviewed change outside fingerprint additions"
    contexts = {}
    for path in sorted(args.base_contexts.iterdir()):
        if not path.is_file() or path.name.endswith(".bin"):
            continue
        other = args.candidate_contexts / path.name
        if path.name == "file_contexts":
            remaining = remove_exact_additions(other.read_text().splitlines(keepends=True), NEW_CONTEXTS)
            assert "".join(remaining) == path.read_text(), "unrelated context change"
        else:
            assert path.read_bytes() == other.read_bytes(), path.name
        contexts[path.name] = digest(path)
    assert "file_contexts" in contexts
    args.report.write_text(json.dumps({
        "status": "passed exact preservation outside the reviewed fingerprint additions",
        "base_policy_sha256": digest(args.base_policy),
        "candidate_policy_sha256": digest(args.candidate_policy),
        "base_decompiled_cil_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "new_top_level_forms": sorted(NEW_FORMS),
        "attribute_additions": {k: sorted(v) for k, v in ATTR_ADDITIONS.items()},
        "preserved_context_text_files": contexts,
        "new_context_lines": sorted(NEW_CONTEXTS),
        "harness_sha256": digest(Path(__file__)),
    }, indent=2) + "\n")
    print("PASS: complete policy structure and existing context text preserved outside reviewed additions")


if __name__ == "__main__":
    main()
