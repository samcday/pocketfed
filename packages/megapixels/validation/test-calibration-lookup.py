#!/usr/bin/env python3
"""Compile and exercise the calibration lookup functions from production dcp.c."""

import argparse
from pathlib import Path
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path, help="patched Megapixels src/dcp.c")
parser.add_argument("--cc", default="cc")
args = parser.parse_args()
source = args.source.read_text()
# Copy exact production functions; camera/profile parsing libraries are unrelated.
functions = source[source.index("char *\nmprintf("):source.index("char *\nmread(")]
functions += source[source.index("bool\nfind_calibration_by_model("):source.index("bool\nfind_calibration(")]
fixture = Path(__file__).with_name("calibration-lookup-fixture.c")
with tempfile.TemporaryDirectory(prefix="megapixels-calibration-test-") as directory:
    work = Path(directory)
    (work / "lookup-functions.c").write_text(functions)
    for location in ("xdg/megapixels/config", "home/.config/megapixels/config",
                     "config", "sysconf/megapixels/config", "data/megapixels/config"):
        (work / location).mkdir(parents=True)
    executable = work / "check-lookup"
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(work), str(fixture), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], cwd=work, check=True, timeout=15)
