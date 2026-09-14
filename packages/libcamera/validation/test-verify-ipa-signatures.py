#!/usr/bin/env python3
"""End-to-end tests for validation/verify-ipa-signatures.

Builds a tiny throwaway RPM whose payload contains the five IPA modules,
signs them with a generated key and runs the verifier through its real CLI.
It exercises a valid package, a modified module, a missing module, a
missing signature, a wrong key and an empty package. The RPMs and keys are
created under a temporary directory and removed afterwards; no device is
touched and no externally supplied package is invoked.
"""

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
VERIFIER = HERE / "verify-ipa-signatures"

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


def test_valid_and_key_forms(tmp):
    require("openssl", "rpmbuild", "rpm2cpio", "cpio")
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

    with tempfile.TemporaryDirectory(prefix="verify-ipa-signatures-test-") as tmp:
        test_valid_and_key_forms(tmp)
        test_modified_bytes(tmp)
        test_missing_module(tmp)
        test_missing_signature(tmp)
        test_empty_package(tmp)
        test_input_errors(tmp)
    print("PASS: valid package, private/public/DER keys, modified bytes, "
          "missing module, missing signature, empty package, input errors")


if __name__ == "__main__":
    sys.exit(main())
