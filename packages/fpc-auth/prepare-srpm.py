#!/usr/bin/env python3
"""Build only an SRPM from explicit local sources; never submit or install it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path, help="new absolute staging directory")
args = parser.parse_args()
output = args.output
if not output.is_absolute() or output.exists():
    parser.error("output must be a new absolute directory")
source = Path(__file__).resolve().parent
shared = source.parent / "fpc-qsee"
files = [
    "auth-broker.c", "auth-store.c", "auth-store.h", "test-auth-store.c", "Makefile",
    "auth-backend.c", "auth-backend.h", "test-auth-backend.c", "pocketfed-fpc-provision@.service",
    "pocketfed-fpc-auth.socket", "pocketfed-fpc-auth.service", "COPYING", "README.md",
    "keymaster-startup.c", "test-keymaster-startup.c", "pocketfed-keymaster-startup.service",
]
shared_files = ["auth-broker.h", "gatekeeper-protocol.c", "gatekeeper-protocol.h",
                "qsee-transport.c", "qsee-transport.h", "protocol.c", "protocol.h"]
output.mkdir(mode=0o700)
for directory in ("SOURCES", "SPECS", "BUILD", "BUILDROOT", "RPMS", "SRPMS"):
    (output / directory).mkdir()
manifest = {}
for directory, names in ((source, files), (shared, shared_files)):
    for name in names:
        content = (directory / name).read_bytes()
        (output / "SOURCES" / name).write_bytes(content)
        manifest[name] = hashlib.sha256(content).hexdigest()
spec = source / "pocketfed-fpc-auth.spec"
shutil.copyfile(spec, output / "SPECS" / spec.name)
manifest[spec.name] = hashlib.sha256(spec.read_bytes()).hexdigest()
(output / "source-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run([
    "rpmbuild", "-bs", "--define", f"_topdir {output}",
    "--define", "dist .fc46", str(output / "SPECS" / spec.name),
], check=True)
for artifact in sorted((output / "SRPMS").glob("*.src.rpm")):
    print(f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact}")
