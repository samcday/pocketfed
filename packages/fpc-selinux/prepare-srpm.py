#!/usr/bin/python3
"""Snapshot only the public module sources and build an SRPM without installing it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
root = args.output
if not root.is_absolute() or root.exists():
    parser.error("output must be a new absolute directory")
source = Path(__file__).resolve().parent
root.mkdir(mode=0o700)
for directory in ("SOURCES", "SPECS", "BUILD", "BUILDROOT", "RPMS", "SRPMS"):
    (root / directory).mkdir()
manifest = {}
for name in ("pocketfed_fpc.te", "pocketfed_fpc.fc", "Makefile",
             "README.package.md", "COPYING", "pocketfed-fpc-selinux.spec"):
    destination = root / ("SPECS" if name.endswith(".spec") else "SOURCES") / name
    shutil.copyfile(source / name, destination)
    manifest[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
for name, target in (("pocketfed_fpc_broker.te", "pocketfed_fpc_broker.te"),
                     ("pocketfed_fpc_broker.fc", "pocketfed_fpc_broker.fc"),
                     ("README.md", "README.broker.md")):
    destination = root / "SOURCES" / target
    shutil.copyfile(source / "broker" / name, destination)
    manifest[target] = hashlib.sha256(destination.read_bytes()).hexdigest()
(root / "source-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run([
    "rpmbuild", "-bs", "--define", f"_topdir {root}", "--define", "dist .fc46",
    str(root / "SPECS/pocketfed-fpc-selinux.spec"),
], check=True)
