#!/usr/bin/python3
"""Reject synthetic policy broadening before querying a merged policy."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

source = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--policy", type=Path, required=True)
parser.add_argument("--contexts", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
te = (source / "pocketfed_fpc.te").read_text()
fc = (source / "pocketfed_fpc.fc").read_text()
cases = {
    "unrelated-existing-file-write": (te + "\nrequire { type etc_t; class file write; }\nallow fprintd_t etc_t:file write;\n", fc),
    "extra-device-map": (te + "\nrequire { class chr_file map; }\nallow fprintd_t pocketfed_fpc_device_t:chr_file map;\n", fc),
    "privileged-tee-label": (te, fc + "\n/dev/teepriv0 -c system_u:object_r:pocketfed_fpc_tee_device_t:s0\n"),
    "private-credential-read": (te + "\nrequire { class file { open read }; }\nallow fprintd_t pocketfed_fpc_auth_state_t:file { open read };\n", fc),
    "broader-service-peer": (te + "\nrequire { type unconfined_service_t; class unix_stream_socket connectto; }\nallow fprintd_t unconfined_service_t:unix_stream_socket connectto;\n", fc),
}
results = []
for name, (mutated_te, mutated_fc) in cases.items():
    with tempfile.TemporaryDirectory(prefix="fpc-policy-mutation-") as directory:
        root = Path(directory)
        shutil.copyfile(source / "test-policy.py", root / "test-policy.py")
        (root / "pocketfed_fpc.te").write_text(mutated_te)
        (root / "pocketfed_fpc.fc").write_text(mutated_fc)
        result = subprocess.run([
            "/usr/bin/python3", str(root / "test-policy.py"),
            "--policy", str(args.policy.resolve()),
            "--contexts", str(args.contexts.resolve()),
        ], text=True, capture_output=True)
        diagnostic = "candidate module contains an unreviewed declaration, rule or file context"
        assert result.returncode != 0 and diagnostic in result.stderr, (name, result.stderr)
        results.append({"case": name, "rejected": True,
                        "returncode": result.returncode, "diagnostic": diagnostic})
args.report.write_text(json.dumps({
    "scope": "synthetic offline mutations; no installed policy change",
    "harness_sha256": hashlib.sha256((source / "test-policy.py").read_bytes()).hexdigest(),
    "results": results,
}, indent=2) + "\n")
print(f"PASS: all {len(results)} policy-broadening mutations rejected at the complete module contract")
