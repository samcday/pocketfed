#!/usr/bin/env python3
"""Exercise production on_frame() with a finite queue of camera buffers."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path, help="patched Megapixels src/io_pipeline.c")
parser.add_argument("--cc", default="cc")
args = parser.parse_args()
source = args.source.read_text()
# Keep the entire production callback, including capture-to-preview transitions.
callback = source[source.index("static void\non_frame("):source.index("static void\ninit_controls(")]
camera_header = args.source.with_name("camera.h").read_text()
buffer_count = re.search(r"^#define MAX_VIDEO_BUFFERS\s+(\d+)\s*$", camera_header, re.MULTILINE)
if buffer_count is None:
    raise SystemExit("Could not read MAX_VIDEO_BUFFERS from production camera.h")

fixture = Path(__file__).with_name("blank-capture-buffers-fixture.c")
with tempfile.TemporaryDirectory(prefix="megapixels-blank-buffer-test-") as directory:
    work = Path(directory)
    (work / "on-frame.c").write_text(callback)
    executable = work / "check-blank-buffers"
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-Wno-unused-parameter", f"-DMAX_VIDEO_BUFFERS={buffer_count[1]}",
                    "-I", str(work), str(fixture), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=15)
