#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Stage explicit local sources and build an SRPM; never install or publish."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path, help="new absolute staging directory")
args = parser.parse_args()
if not args.output.is_absolute() or args.output.exists():
    parser.error("output must be a new absolute directory")
source = Path(__file__).resolve().parent
name = "plymouth-theme-fedora-mobile-0.1.0"
files = ("fedora-mobile.plymouth", "generate-assets.py", "test-assets.py", "LICENSE", "README.md")
for directory in ("SOURCES", "SPECS", "BUILD", "BUILDROOT", "RPMS", "SRPMS"):
    (args.output / directory).mkdir(parents=True)
manifest = {}
payload = io.BytesIO()
with tarfile.open(fileobj=payload, mode="w") as archive:
    for filename in files:
        content = (source / filename).read_bytes()
        manifest[filename] = hashlib.sha256(content).hexdigest()
        info = tarfile.TarInfo(f"{name}/{filename}")
        info.size, info.mode, info.mtime = len(content), 0o644, 1789084800
        archive.addfile(info, io.BytesIO(content))
(args.output / "SOURCES" / f"{name}.tar.gz").write_bytes(gzip.compress(payload.getvalue(), mtime=0))
spec = source / "plymouth-theme-fedora-mobile.spec"
shutil.copyfile(spec, args.output / "SPECS" / spec.name)
manifest[spec.name] = hashlib.sha256(spec.read_bytes()).hexdigest()
(args.output / "source-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run(["rpmbuild", "-bs", "--define", f"_topdir {args.output}",
                "--define", "dist .fc46", str(args.output / "SPECS" / spec.name)], check=True)
