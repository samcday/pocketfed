#!/usr/bin/python3
"""Compile and query the candidate against an offline image policy, without loading it."""
import argparse
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

import setools


SOURCE = Path(__file__).resolve().parent
DEVICE_TYPES = {"pocketfed_fpc_device_t", "pocketfed_fpc_tee_device_t"}
STATE_TYPE = "pocketfed_fpc_auth_state_t"
RUN_TYPE = "pocketfed_fpc_auth_run_t"
TYPES = DEVICE_TYPES | {STATE_TYPE, RUN_TYPE}
EXPECTED = {"getattr", "open", "read", "write", "ioctl"}
IOCTLS = {
    "pocketfed_fpc_device_t": {0x4600, 0x4601, 0x4602},
    "pocketfed_fpc_tee_device_t": {0xa400, 0xa401, 0xa402, 0xa403, 0xa405},
}

EXPECTED_MODULE_CIL = r'''
(type pocketfed_fpc_device_t)
(roletype object_r pocketfed_fpc_device_t)
(type pocketfed_fpc_tee_device_t)
(roletype object_r pocketfed_fpc_tee_device_t)
(type pocketfed_fpc_auth_state_t)
(roletype object_r pocketfed_fpc_auth_state_t)
(type pocketfed_fpc_auth_run_t)
(roletype object_r pocketfed_fpc_auth_run_t)
(typeattributeset cil_gen_require fprintd_t)
(typeattributeset cil_gen_require init_t)
(typeattributeset cil_gen_require device_node)
(typeattributeset device_node (pocketfed_fpc_device_t pocketfed_fpc_tee_device_t))
(typeattributeset cil_gen_require file_type)
(typeattributeset file_type (pocketfed_fpc_auth_state_t pocketfed_fpc_auth_run_t))
(typeattributeset cil_gen_require non_auth_file_type)
(typeattributeset non_auth_file_type (pocketfed_fpc_auth_state_t pocketfed_fpc_auth_run_t))
(typeattributeset cil_gen_require non_security_file_type)
(typeattributeset non_security_file_type (pocketfed_fpc_auth_state_t pocketfed_fpc_auth_run_t))
(typeattributeset cil_gen_require pidfile)
(typeattributeset pidfile (pocketfed_fpc_auth_run_t))
(allow init_t pocketfed_fpc_auth_state_t (dir (create setattr)))
(allow fprintd_t pocketfed_fpc_auth_run_t (dir (search)))
(allow fprintd_t pocketfed_fpc_auth_run_t (sock_file (getattr write)))
(allow fprintd_t pocketfed_fpc_device_t (chr_file (getattr open read write ioctl)))
(allow fprintd_t pocketfed_fpc_tee_device_t (chr_file (getattr open read write ioctl)))
(allowx fprintd_t pocketfed_fpc_device_t (ioctl chr_file ((range 0x4600 0x4602))))
(allowx fprintd_t pocketfed_fpc_tee_device_t (ioctl chr_file ((range 0xa400 0xa403) 0xa405)))
(filecon "/dev/fpc1020" char (system_u object_r pocketfed_fpc_device_t ((s0) (s0))))
(filecon "/dev/tee([0-9]|1[0-5])" char (system_u object_r pocketfed_fpc_tee_device_t ((s0) (s0))))
(filecon "/var/lib/pocketfed-fpc-auth(/.*)?" any (system_u object_r pocketfed_fpc_auth_state_t ((s0) (s0))))
(filecon "/run/pocketfed-fpc-auth" dir (system_u object_r pocketfed_fpc_auth_run_t ((s0) (s0))))
(filecon "/run/pocketfed-fpc-auth/token\.sock" socket (system_u object_r pocketfed_fpc_auth_run_t ((s0) (s0))))
'''


def cil_forms(text):
    """Read the generated module's S-expressions, including quoted path regexes."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars="()")
    lexer.whitespace_split = True
    lexer.commenters = ";"
    stack, result = [], []
    for token in lexer:
        tokens = list(token) if set(token) <= {"(", ")"} else [token]
        for atom in tokens:
            if atom == "(":
                stack.append([])
            elif atom == ")":
                assert stack, "unbalanced generated CIL"
                form = tuple(stack.pop())
                (stack[-1] if stack else result).append(form)
            else:
                assert stack, "atom outside generated CIL form"
                stack[-1].append(atom)
    assert not stack, "unterminated generated CIL"
    return sorted(result, key=repr)


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          capture_output=True, **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_cil(files, output, version, mls):
    """Use libsepol's public CIL API, equivalent to an offline secilc invocation."""
    lib = ctypes.CDLL(ctypes.util.find_library("sepol"))
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    ptr, size = ctypes.c_void_p, ctypes.c_size_t
    signatures = {
        "cil_db_init": (None, [ctypes.POINTER(ptr)]),
        "cil_db_destroy": (None, [ctypes.POINTER(ptr)]),
        "cil_add_file": (ctypes.c_int, [ptr, ctypes.c_char_p, ctypes.c_char_p, size]),
        "cil_set_mls": (None, [ptr, ctypes.c_int]),
        "cil_set_policy_version": (None, [ptr, ctypes.c_int]),
        "cil_compile": (ctypes.c_int, [ptr]),
        "cil_build_policydb": (ctypes.c_int, [ptr, ctypes.POINTER(ptr)]),
        "sepol_policydb_to_image": (ctypes.c_int, [ptr, ptr, ctypes.POINTER(ptr), ctypes.POINTER(size)]),
        "sepol_policydb_free": (None, [ptr]),
    }
    for name, (result, arguments) in signatures.items():
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, arguments
    libc.free.restype, libc.free.argtypes = None, [ptr]
    db, pdb, image, length = ptr(), ptr(), ptr(), size()
    lib.cil_db_init(ctypes.byref(db))
    buffers = []
    try:
        lib.cil_set_mls(db, int(mls))
        lib.cil_set_policy_version(db, version)
        for path in files:
            data = Path(path).read_bytes()
            buffers.append(data)
            assert lib.cil_add_file(db, str(path).encode(), data, len(data)) == 0
        assert lib.cil_compile(db) == 0, "CIL compilation failed"
        assert lib.cil_build_policydb(db, ctypes.byref(pdb)) == 0
        assert lib.sepol_policydb_to_image(None, pdb, ctypes.byref(image), ctypes.byref(length)) == 0
        output.write_bytes(ctypes.string_at(image, length.value))
    finally:
        if image:
            libc.free(image)
        if pdb:
            lib.sepol_policydb_free(pdb)
        lib.cil_db_destroy(ctypes.byref(db))


def rules(policy, target, kind="allow", cls="chr_file", source="fprintd_t"):
    return list(setools.TERuleQuery(policy, ruletype=[kind], source=source,
                                  target=target, tclass=[cls]).results())


def enabled(rule):
    try:
        return rule.conditional_block == rule.conditional.evaluate()
    except setools.exception.RuleNotConditional:
        return True


def perms(policy, target, cls="chr_file"):
    return set().union(*(set(r.perms) for r in rules(policy, target, cls=cls) if enabled(r)))


def context(path, mode, database):
    return run("/usr/sbin/matchpathcon", "-n", "-N", "-m", mode,
               "-f", database, path).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--merged-policy", type=Path,
                        help="query a separately rebuilt module-store policy")
    parser.add_argument("--merged-contexts", type=Path,
                        help="file_contexts from that same module-store rebuild")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if bool(args.merged_policy) != bool(args.merged_contexts):
        parser.error("--merged-policy and --merged-contexts must be supplied together")
    before = setools.SELinuxPolicy(str(args.policy))
    assert not before.lookup_type("fprintd_t").ispermissive
    assert not TYPES.intersection(str(t) for t in before.types()), "candidate is already installed"
    with tempfile.TemporaryDirectory(prefix="fpc-selinux-offline-") as directory:
        tmp = Path(directory)
        module, package = tmp / "pocketfed_fpc.mod", tmp / "pocketfed_fpc.pp"
        run("/usr/bin/checkmodule", "-M", "-m", "-o", module, SOURCE / "pocketfed_fpc.te")
        run("/usr/bin/semodule_package", "-o", package, "-m", module,
            "-f", SOURCE / "pocketfed_fpc.fc")
        base_cil, module_cil = tmp / "base.cil", tmp / "module.cil"
        run("/usr/bin/checkpolicy", "-M", "-b", "-C", "-o", base_cil, args.policy)
        # libsemanage normally supplies this bookkeeping attribute while linking
        # modules. A decompiled kernel policy omits it; declare it for this
        # isolated compilation without changing the candidate's policy rules.
        generated_cil = run("/usr/libexec/selinux/hll/pp", package).stdout
        # Merged queries for just the new types cannot detect a stray grant to
        # some existing target. Reject every unreviewed module form first,
        # including extra allows, attributes, transitions, labels or conditions.
        assert cil_forms(generated_cil) == cil_forms(EXPECTED_MODULE_CIL), \
            "candidate module contains an unreviewed declaration, rule or file context"
        module_cil.write_text("(typeattribute cil_gen_require)\n" + generated_cil)
        output = tmp / "policy.merged"
        if args.merged_policy:
            shutil.copyfile(args.merged_policy, output)
        else:
            build_cil([base_cil, module_cil], output, before.version, before.mls)
        after = setools.SELinuxPolicy(str(output))
        assert {str(t) for t in after.types()} - {str(t) for t in before.types()} == TYPES
        assert not after.lookup_type("fprintd_t").ispermissive
        result = {}
        for target in sorted(DEVICE_TYPES):
            assert {str(a) for a in after.lookup_type(target).attributes()} == {"device_node"}
            assert perms(after, target) == EXPECTED, (target, perms(after, target))
            # A default-disabled conditional rule must not hide extra grants.
            assert set().union(*(set(r.perms) for r in rules(after, target))) == EXPECTED
            xperms = set().union(*(set(r.perms) for r in rules(after, target, "allowxperm") if enabled(r)))
            assert xperms == IOCTLS[target], (target, xperms)
            assert set().union(*(set(r.perms) for r in rules(after, target, "allowxperm"))) == IOCTLS[target]
            # Existing device_node administration and unconfined QSEE services
            # must retain their normal access; this module adds no such rules.
            administration = set().union(*(set(r.perms) for r in rules(
                after, target, source="udev_t") if enabled(r)))
            assert {"getattr", "relabelto"} <= administration
            qsee = set().union(*(set(r.perms) for r in rules(
                after, target, source="unconfined_service_t") if enabled(r)))
            assert EXPECTED <= qsee
            result[target] = {"permissions": sorted(perms(after, target)),
                              "ioctl_low16": [f"0x{x:04x}" for x in sorted(xperms)]}
        # Keep service credentials outside fprintd's state type. Check all
        # conditional branches so a boolean cannot silently add data access.
        for target, extra in [(STATE_TYPE, set()), (RUN_TYPE, {"pidfile"})]:
            assert {str(a) for a in after.lookup_type(target).attributes()} == {
                "file_type", "non_auth_file_type", "non_security_file_type"} | extra
        all_perms = lambda source, target, cls: set().union(*(set(r.perms) for r in
            rules(after, target, cls=cls, source=source)))
        forbidden_file = {"read", "write", "open", "append", "create", "unlink", "setattr"}
        credential_access = all_perms("fprintd_t", STATE_TYPE, "file")
        assert not credential_access & forbidden_file, credential_access
        assert all_perms("fprintd_t", RUN_TYPE, "sock_file") == {"getattr", "write"}
        assert "search" in all_perms("fprintd_t", RUN_TYPE, "dir")
        assert not all_perms("fprintd_t", RUN_TYPE, "dir") & {"create", "write", "add_name", "remove_name", "setattr"}
        assert {"create", "setattr"} <= all_perms("init_t", STATE_TYPE, "dir")
        assert {"create", "setattr", "write", "unlink"} <= all_perms("init_t", RUN_TYPE, "sock_file")
        assert {"open", "read", "write", "create", "setattr", "unlink"} <= all_perms(
            "unconfined_service_t", STATE_TYPE, "file")
        peer_before = sorted(str(r) for r in rules(before, "init_t", cls="unix_stream_socket"))
        peer_after = sorted(str(r) for r in rules(after, "init_t", cls="unix_stream_socket"))
        assert peer_before == peer_after
        assert "connectto" in perms(after, "init_t", cls="unix_stream_socket")
        result[STATE_TYPE] = {"fprintd_file_permissions_all_branches": sorted(credential_access),
                              "credential_data_access_denied": True}
        result[RUN_TYPE] = {"fprintd_socket_permissions": ["getattr", "write"],
                            "existing_init_peer_permission_preserved": True,
                            "activation_peer_runtime": "requires supplementary broker-domain policy"}
        # Existing generic devices, broker socket and service transitions stay unchanged.
        for target, cls in [("device_t", "chr_file"), ("var_run_t", "sock_file")]:
            for kind in ["allow", "allowxperm"]:
                assert sorted(str(r) for r in rules(before, target, kind, cls)) == sorted(
                    str(r) for r in rules(after, target, kind, cls))
        transitions = lambda p: sorted(str(r) for r in setools.TERuleQuery(
            p, ruletype=["type_transition"], source="init_t", tclass=["process"]).results())
        assert transitions(before) == transitions(after)

        # Test the actual libselinux matcher with image substitutions/local overrides.
        fc = tmp / "file_contexts"
        context_source = args.merged_contexts or args.contexts
        for source in context_source.parent.glob(context_source.name + "*"):
            if not source.name.endswith(".bin"):
                shutil.copyfile(source, tmp / source.name)
        if not args.merged_contexts:
            with fc.open("a") as stream:
                stream.write("\n" + (SOURCE / "pocketfed_fpc.fc").read_text())
        contexts = {}
        for path in ["/dev/fpc1020"] + [f"/dev/tee{i}" for i in range(16)]:
            expected = "pocketfed_fpc_device_t" if path == "/dev/fpc1020" else "pocketfed_fpc_tee_device_t"
            value = context(path, "chr_file", fc)
            assert value.split(":")[2] == expected, (path, value)
            contexts[path] = value
        for path, mode, expected in [
            ("/var/lib/pocketfed-fpc-auth", "dir", STATE_TYPE),
            ("/var/lib/pocketfed-fpc-auth/.lock", "file", STATE_TYPE),
            ("/var/lib/pocketfed-fpc-auth/uid-1000.intent", "file", STATE_TYPE),
            ("/var/lib/pocketfed-fpc-auth/uid-1000.credential", "file", STATE_TYPE),
            ("/run/pocketfed-fpc-auth", "dir", RUN_TYPE),
            ("/run/pocketfed-fpc-auth/token.sock", "sock_file", RUN_TYPE),
        ]:
            value = context(path, mode, fc)
            assert value.split(":")[2] == expected, (path, value)
            contexts[path] = value
        negatives = ["/dev/teepriv0", "/dev/teepriv15", "/dev/tee16", "/dev/tee99",
                     "/dev/tee00", "/dev/tee01", "/dev/tee", "/dev/fpc10200",
                     "/dev/fpc1020/child", "/run/pocketfed-fpc-auth/other.sock",
                     "/var/lib/pocketfed-fpc-auth-other/uid-1000.credential",
                     "/usr/bin/pocketfed-fpc-auth"]
        for path in negatives:
            mode = "sock_file" if path.startswith("/run/") else "chr_file" if path.startswith("/dev/") else "file"
            assert context(path, mode, fc) == context(path, mode, args.contexts), path
        for path in ["/dev/fpc1020", "/dev/tee0", "/dev/tee15"]:
            for mode in ["file", "dir", "sock_file"]:
                assert context(path, mode, fc) == context(path, mode, args.contexts), (path, mode)
        for path, modes in [("/run/pocketfed-fpc-auth", ["file", "sock_file"]),
                            ("/run/pocketfed-fpc-auth/token.sock", ["file", "dir"])]:
            for mode in modes:
                assert context(path, mode, fc) == context(path, mode, args.contexts), (path, mode)
        report = {
            "status": "offline compile and query tests passed; not loaded or runtime-tested",
            "base_policy_sha256": digest(args.policy),
            "base_policy_version": before.version,
            "candidate_sources": {p.name: digest(p) for p in [SOURCE / "pocketfed_fpc.te", SOURCE / "pocketfed_fpc.fc"]},
            "module_pp_sha256": digest(package),
            "merged_policy_sha256": digest(output),
            "merged_policy_origin": "external module-store rebuild" if args.merged_policy else "binary-to-CIL fixture",
            "grants": result,
            "positive_contexts": contexts,
            "negative_contexts_unchanged": negatives,
            "tests": ["module compile/package", "exact complete module declaration/rule/filecon contract",
                      "image binary to CIL and merged binary compile",
                      "exact added types/attributes", "exact fprintd permissions and ioctl sets including disabled branches",
                      "existing udev relabel and QSEE service access preserved",
                      "generic device and runtime-object rules unchanged", "service transitions unchanged",
                      "fprintd private credential access denied including conditional branches",
                      "broker socket inode access and unchanged existing init_t peer permissions",
                      "fprintd remains confined", "exact positive/negative path and inode-class labels"],
            "limits": "queries do not establish source neverallow results, kernel policy loading, udev labels or actual hardware access; external module-store build provenance is recorded separately",
            "audit_inputs": {str(p.relative_to(SOURCE.parent.parent)): digest(p) for p in [
                SOURCE.parent / "fpc-qsee/sensor.c", SOURCE.parent / "fpc-qsee/qsee-transport.c",
                SOURCE.parent / "fpc-qsee/fpc1020.h"] if p.exists()},
            "validation_harness_sha256": digest(Path(__file__)),
        }
        if args.report:
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        print("PASS: offline module compile, merged policy queries, exact labels and negative boundaries")


if __name__ == "__main__":
    main()
