#!/usr/bin/python3
"""Preserve vendored crates' distributed license and copyright notices."""
from pathlib import Path
import shutil

output = Path("LICENSE.vendor")
output.mkdir(exist_ok=True)
for crate in sorted(Path("vendor").iterdir()):
    if not crate.is_dir():
        continue
    for source in sorted(crate.iterdir()):
        if source.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "COPYRIGHT", "NOTICE")):
            destination = output / crate.name / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copyfile(source, destination)
