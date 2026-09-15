#!/usr/bin/env python3
"""End-to-end tests for validation/verify-ipa-signatures.

Builds a tiny throwaway RPM whose payload contains the five IPA modules,
signs them with a generated key and runs the verifier through its real CLI.
It exercises a valid package, a modified module, a missing module, a
missing signature, a wrong key, an empty package and an encrypted key that
must not prompt. It also drives the bounded cpio reader directly with
crafted payloads containing path traversal, key-collision, symlink and
duplicate members. The RPMs and keys are created under a temporary
directory and removed afterwards; no device is touched and no externally
supplied package is invoked.
"""

from pathlib import Path
import io
import json
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
VERIFIER = HERE / "verify-ipa-signatures"
API = {}

MODULES = (
    "ipa_mali_c55",
    "ipa_rkisp1",
    "ipa_rpi_vc4",
    "ipa_soft_simple",
    "ipa_vimc",
)

SPEC = """\
Name: ipa-signature-fixture
Version: 1
Release: 1
Summary: verifier fixture
License: MIT
BuildArch: noarch
%global debug_package %{nil}
%global __os_install_post %{nil}
%description
verifier fixture
%install
mkdir -p %{buildroot}/usr/lib64/libcamera/ipa
cp -a %{_sourcedir}/payload/. %{buildroot}/usr/lib64/libcamera/ipa/
%files
/usr/lib64/libcamera/ipa
"""


def require(*tools):
    for tool in tools:
        assert shutil.which(tool), f"missing required tool: {tool}"


def generate_key(root, name):
    private = root / f"{name}.pem"
    public = root / f"{name}.pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", str(private),
                    "-pkeyopt", "rsa_keygen_bits:2048"],
                   stderr=subprocess.DEVNULL, check=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout",
                    "-out", str(public)], stderr=subprocess.DEVNULL, check=True)
    return private, public


def make_payload(root, modules=MODULES):
    payload = root / "payload"
    payload.mkdir(parents=True)
    for module in modules:
        (payload / f"{module}.so").write_text(f"fixture module {module}\n")
    return payload


def sign(payload, private, modules=None):
    if modules is None:
        modules = [path.name[:-3] for path in sorted(payload.glob("*.so"))]
    for module in modules:
        module_path = payload / f"{module}.so"
        assert module_path.is_file(), f"cannot sign absent {module_path}"
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(private),
                        "-out", str(module_path) + ".sign", str(module_path)],
                       stderr=subprocess.DEVNULL, check=True)


def build_rpm(root, payload, name):
    top = root / name
    sources = top / "SOURCES"
    sources.mkdir(parents=True)
    shutil.copytree(payload, sources / "payload")
    spec = top / "fixture.spec"
    spec.write_text(SPEC)
    result = subprocess.run(["rpmbuild", "-bb", "--define", f"_topdir {top}", str(spec)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            check=False)
    assert result.returncode == 0, f"rpmbuild failed:\n{result.stdout}"
    rpms = list((top / "RPMS").rglob("*.rpm"))
    assert len(rpms) == 1, f"expected one fixture RPM, got {rpms}"
    return rpms[0]


def verify(rpm, key):
    result = subprocess.run([str(VERIFIER), "--rpm", str(rpm), "--key", str(key)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            check=False)
    assert result.stdout, f"no JSON on stdout; stderr={result.stderr}"
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as failure:
        raise AssertionError(f"invalid JSON output: {failure}\n{result.stdout}")
    return result.returncode, document


def statuses(document):
    return {entry["name"]: entry["status"] for entry in document["modules"]}


def newc_entry(name, data=b"", mode=0o100644, ino=1):
    name_bytes = name.encode("ascii") + b"\0"
    fields = (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name_bytes), 0)
    header = b"070701" + b"".join(f"{value:08x}".encode("ascii") for value in fields)
    padding = b"\0" * ((-(110 + len(name_bytes))) % 4)
    return header + name_bytes + padding + data + b"\0" * ((-len(data)) % 4)


def newc_archive(members):
    blob = bytearray()
    for index, (name, data, mode) in enumerate(members, start=1):
        blob += newc_entry(name, data, mode, ino=index)
    blob += newc_entry("TRAILER!!!", b"", 0, ino=len(members) + 1)
    return bytes(blob)


def test_valid_and_key_forms(tmp):
    require("openssl", "rpmbuild", "rpm2cpio")
    assert VERIFIER.stat().st_mode & 0o111, "verifier is not executable"

    root = Path(tmp)
    private, public = generate_key(root, "key-a")
    payload = make_payload(root / "valid")
    sign(payload, private)
    rpm = build_rpm(root / "valid", payload, "valid")

    code, document = verify(rpm, public)
    assert code == 0 and document["ok"], document
    assert statuses(document) == {module: "valid" for module in MODULES}, document
    assert document["key"]["kind"] == "public"
    assert document["failures"] == []
    assert all(len(entry["sha256"]) == 64 for entry in document["modules"])
    assert len(document["rpm"]["sha256"]) == 64
    public_hash = document["key"]["sha256"]

    code, via_private = verify(rpm, private)
    assert code == 0 and via_private["ok"], via_private
    assert via_private["key"] == {"kind": "private-derived", "sha256": public_hash}
    text = json.dumps(via_private)
    assert "PRIVATE KEY" not in text
    private_body = [line for line in private.read_text().splitlines()
                    if line and not line.startswith("-----")][0]
    assert private_body not in text, "private key material leaked into output"

    public_der = root / "key-a.pub.der"
    subprocess.run(["openssl", "pkey", "-pubin", "-in", str(public),
                    "-outform", "DER", "-out", str(public_der)],
                   stderr=subprocess.DEVNULL, check=True)
    code, via_der = verify(rpm, public_der)
    assert code == 0 and via_der["ok"], via_der
    assert via_der["key"] == {"kind": "public", "sha256": public_hash}

    private_der = root / "key-a.priv.der"
    subprocess.run(["openssl", "pkey", "-in", str(private), "-outform", "DER",
                    "-out", str(private_der)],
                   stderr=subprocess.DEVNULL, check=True)
    code, via_private_der = verify(rpm, private_der)
    assert code == 0 and via_private_der["ok"], via_private_der
    assert via_private_der["key"] == {"kind": "private-derived",
                                      "sha256": public_hash}

    _, wrong_public = generate_key(root, "key-b")
    code, document = verify(rpm, wrong_public)
    assert code != 0 and not document["ok"], document
    assert set(statuses(document).values()) == {"invalid"}, document
    assert len(document["failures"]) == len(MODULES)

    encrypted = root / "key-a.encrypted.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-aes-256-cbc",
                    "-pass", "pass:secret", "-pkeyopt", "rsa_keygen_bits:2048",
                    "-out", str(encrypted)],
                   stderr=subprocess.DEVNULL, check=True)
    prompted = subprocess.run([str(VERIFIER), "--rpm", str(rpm), "--key", str(encrypted)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              timeout=30, check=False)
    encrypted_document = json.loads(prompted.stdout)
    assert prompted.returncode != 0 and not encrypted_document["ok"], encrypted_document
    assert "PRIVATE KEY" not in prompted.stdout


def test_modified_bytes(tmp):
    root = Path(tmp)
    private, public = generate_key(root, "key")
    payload = make_payload(root / "modified")
    sign(payload, private)
    target = payload / "ipa_rkisp1.so"
    target.write_bytes(target.read_bytes() + b"tamper\n")
    rpm = build_rpm(root / "modified", payload, "modified")

    code, document = verify(rpm, public)
    assert code != 0 and not document["ok"], document
    assert statuses(document)["ipa_rkisp1"] == "invalid", document
    for module in MODULES:
        if module != "ipa_rkisp1":
            assert statuses(document)[module] == "valid", document


def test_missing_module(tmp):
    root = Path(tmp)
    private, public = generate_key(root, "key")
    payload = make_payload(root / "missing-module",
                           [module for module in MODULES if module != "ipa_vimc"])
    sign(payload, private)
    rpm = build_rpm(root / "missing-module", payload, "missing-module")

    code, document = verify(rpm, public)
    assert code != 0 and not document["ok"], document
    assert statuses(document)["ipa_vimc"] == "missing-module", document
    assert "ipa_vimc: missing-module" in document["failures"]


def test_missing_signature(tmp):
    root = Path(tmp)
    private, public = generate_key(root, "key")
    payload = make_payload(root / "missing-signature")
    sign(payload, private, [module for module in MODULES if module != "ipa_vimc"])
    rpm = build_rpm(root / "missing-signature", payload, "missing-signature")

    code, document = verify(rpm, public)
    assert code != 0 and not document["ok"], document
    assert statuses(document)["ipa_vimc"] == "missing-signature", document
    assert "ipa_vimc: missing-signature" in document["failures"]


def test_empty_package(tmp):
    root = Path(tmp)
    private, public = generate_key(root, "key")
    payload = make_payload(root / "empty", [])
    rpm = build_rpm(root / "empty", payload, "empty")

    code, document = verify(rpm, public)
    assert code != 0 and not document["ok"], document
    assert set(statuses(document).values()) == {"missing-module"}, document


def test_bounded_reader(tmp):
    read_cpio = API["read_cpio"]
    root = Path(tmp)
    members = []
    for module in MODULES:
        members.append((f"./usr/lib64/libcamera/ipa/{module}.so",
                        f"{module} bytes\n".encode(), 0o100755))
        members.append((f"./usr/lib64/libcamera/ipa/{module}.so.sign",
                        b"signature\n", 0o100644))

    clean = root / "clean"
    read_cpio(io.BytesIO(newc_archive(members)), clean)
    for module in MODULES:
        module_path = clean / "usr/lib64/libcamera/ipa" / f"{module}.so"
        sign_path = clean / "usr/lib64/libcamera/ipa" / f"{module}.so.sign"
        assert module_path.read_bytes() == f"{module} bytes\n".encode()
        assert sign_path.read_bytes() == b"signature\n"
    assert len(list((clean / "usr/lib64/libcamera/ipa").iterdir())) == 10

    key_dir = root / "trusted"
    key_dir.mkdir()
    trusted = key_dir / "public.der"
    trusted.write_bytes(b"trusted key bytes")

    hostile = newc_archive(members + [
        ("../../escape", b"escape\n", 0o100644),
        ("./../../public.der", b"evil\n", 0o100644),
        ("./usr/lib64/libcamera/ipa/../../../../public.der", b"evil\n", 0o100644),
        ("./public.der", b"evil\n", 0o100644),
        ("./usr/lib64/libcamera/ipa/public.der", b"evil\n", 0o100644),
    ])
    read_cpio(io.BytesIO(hostile), root / "hostile")
    assert not (root / "escape").exists()
    assert not (root / "hostile" / "escape").exists()
    assert not (root / "hostile" / "public.der").exists()
    assert not (root / "hostile" / "usr/lib64/libcamera/ipa" / "public.der").exists()
    assert len(list((root / "hostile" / "usr/lib64/libcamera/ipa").iterdir())) == 10
    assert trusted.read_bytes() == b"trusted key bytes"

    for label, member in (
            ("symlink", ("./usr/lib64/libcamera/ipa/ipa_vimc.so", b"", 0o120777)),
            ("non-regular", ("./usr/lib64/libcamera/ipa/ipa_vimc.so", b"", 0o040755))):
        try:
            read_cpio(io.BytesIO(newc_archive([member])), root / label)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{label} member accepted")

    duplicates = [
        ("./usr/lib64/libcamera/ipa/ipa_vimc.so", b"a", 0o100644),
        ("./usr/lib64/libcamera/ipa/ipa_vimc.so", b"b", 0o100644),
    ]
    try:
        read_cpio(io.BytesIO(newc_archive(duplicates)), root / "duplicate")
    except RuntimeError:
        pass
    else:
        raise AssertionError("duplicate member accepted")

    for label, member in (
            ("unexpected-module",
             ("./usr/lib64/libcamera/ipa/ipa_extra.so", b"", 0o100644)),
            ("unexpected-signature",
             ("./usr/lib64/libcamera/ipa/ipa_extra.so.sign", b"", 0o100644)),
            ("nested-unexpected-module",
             ("./usr/lib64/libcamera/ipa/nested/ipa_extra.so", b"", 0o100644))):
        try:
            read_cpio(io.BytesIO(newc_archive([member])), root / label)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"{label} member accepted")


def test_unexpected_ipa_members(tmp):
    root = Path(tmp)
    private, public = generate_key(root, "key")

    extra = make_payload(root / "extra-module", MODULES + ("ipa_extra",))
    sign(extra, private, MODULES)
    extra_rpm = build_rpm(root / "extra-module", extra, "extra-module")
    code, document = verify(extra_rpm, public)
    assert code != 0 and not document["ok"], document
    assert "unexpected" in document["error"], document

    orphan = make_payload(root / "orphan-signature")
    sign(orphan, private)
    (orphan / "ipa_extra.so.sign").write_bytes(b"orphan signature\n")
    orphan_rpm = build_rpm(root / "orphan-signature", orphan, "orphan-signature")
    code, document = verify(orphan_rpm, public)
    assert code != 0 and not document["ok"], document
    assert "unexpected" in document["error"], document


def test_input_errors(tmp):
    root = Path(tmp)
    _, public = generate_key(root, "key")
    code, document = verify(root / "absent.rpm", public)
    assert code != 0 and not document["ok"] and "not found" in document["error"]

    code, document = verify(VERIFIER, root / "absent.pem")
    assert code != 0 and not document["ok"] and "not found" in document["error"]

    garbage = root / "garbage.pem"
    garbage.write_text("not a key\n")
    code, document = verify(VERIFIER, garbage)
    assert code != 0 and not document["ok"] and "key" in document["error"]


def main():
    assert VERIFIER.is_file(), f"missing {VERIFIER}"
    namespace = {"__name__": "verify_ipa_signatures_under_test"}
    exec(compile(VERIFIER.read_text(), str(VERIFIER), "exec"), namespace)
    assert tuple(namespace["MODULES"]) == MODULES, "verifier module list changed"
    API.update(namespace)

    with tempfile.TemporaryDirectory(prefix="verify-ipa-signatures-test-") as tmp:
        test_valid_and_key_forms(tmp)
        test_modified_bytes(tmp)
        test_missing_module(tmp)
        test_missing_signature(tmp)
        test_empty_package(tmp)
        test_bounded_reader(tmp)
        test_unexpected_ipa_members(tmp)
        test_input_errors(tmp)
    print("PASS: valid package, private/public/DER keys, encrypted key no-prompt, "
          "modified bytes, missing module, missing signature, empty package, "
          "bounded reader traversal/collision/symlink/duplicate/unexpected, "
          "unexpected extra module and orphan signature, input errors")


if __name__ == "__main__":
    sys.exit(main())
