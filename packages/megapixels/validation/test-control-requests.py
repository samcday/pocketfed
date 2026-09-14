#!/usr/bin/env python3
"""Exercise production camera control functions with sensor and IO fixtures."""

import argparse
from pathlib import Path
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path, help="patched Megapixels source directory")
parser.add_argument("--cc", default="cc")
args = parser.parse_args()
process = (args.source / "src/process_pipeline.c").read_text()
io = (args.source / "src/io_pipeline.c").read_text()
main = (args.source / "src/main.c").read_text()


def section(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


# Compile the exact production functions. The fixture replaces camera IO and
# supplies scene statistics; it neither opens camera devices nor needs a GPU.
functions = "\n".join([
    section(process, "float\nclamp_float(", "static int focus;"),
    section(process, "static void\nupdate_exp(", "static int exposure_limit;"),
    section(process, "static void\nprocess_aaa()",
            "static GdkTexture *\nprocess_image_for_preview("),
    section(io, "static void\ninit_controls()",
            "/*\n * State transfer from Main -> IO"),
    section(io, "static void\nupdate_controls()",
            "static void\ndo_aaa()" if "static void\ndo_aaa()" in io
            else "static void\non_frame("),
    section(main, "static void\nset_gain_auto(", "static void\nopen_iso_controls("),
    section(main, "static void\nset_shutter_auto(", "static void\nset_focus("),
    section(main, "static void\nset_focus_auto(", "static void\nopen_shutter_controls("),
])
fixture = Path(__file__).with_name("control-requests-fixture.c")
with tempfile.TemporaryDirectory(prefix="megapixels-controls-test-") as directory:
    work = Path(directory)
    (work / "control-functions.c").write_text(functions)
    executable = work / "check-controls"
    subprocess.run([args.cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(work), str(fixture), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], cwd=work, check=True, timeout=15)
