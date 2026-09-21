#!/usr/bin/env python3
"""Pull the GLSL sources of specific glShaderSource() calls out of an
apitrace text dump, so the host harness can compile the *exact* shaders the
device saw.

The shader text belongs to whatever application was traced; it is extracted to
a scratch directory at analysis time and is deliberately not committed here.

usage: extract-shaders.py <apitrace-dump.txt> <outdir> [call:name ...]

With no call:name pairs the defaults below are used, which are the four GSK
gradient shaders of the pocketfed#80 r3 trace:
  4925:p3_vs 4961:p3_fs   GSK_FLAGS=0u, GSK_SHADER_CLIP == CLIP_NONE  (passes)
  5989:p7_vs 5993:p7_fs   GSK_FLAGS=2u, GSK_SHADER_CLIP == ROUNDED    (hangs)
"""
import os
import re
import sys

DEFAULTS = {4925: "p3_vs", 4961: "p3_fs", 5989: "p7_vs", 5993: "p7_fs"}


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    dump, outdir = argv[1], argv[2]
    if len(argv) > 3:
        want = {}
        for spec in argv[3:]:
            call, name = spec.split(":", 1)
            want[int(call)] = name
    else:
        want = DEFAULTS

    src = open(dump, encoding="utf-8", errors="replace").read()
    os.makedirs(outdir, exist_ok=True)

    for callno, name in want.items():
        m = re.search(
            r"^%d glShaderSource\(shader = \d+, count = (\d+), string = \{" % callno,
            src,
            re.M,
        )
        if not m:
            sys.exit("call %d is not a glShaderSource in %s" % (callno, dump))
        start = m.end()
        end = src.index("}, length =", start)
        body = src[start:end].rstrip()
        if not (body.startswith('"') and body.endswith('"')):
            sys.exit("call %d: unexpected string encoding" % callno)
        parts = body[1:-1].split('", "')
        if len(parts) != int(m.group(1)):
            sys.exit("call %d: expected %s strings, got %d"
                     % (callno, m.group(1), len(parts)))
        path = os.path.join(outdir, name + ".glsl")
        open(path, "w").write("".join(parts))
        print("%s <- call %d (%d bytes)"
              % (path, callno, sum(len(p) for p in parts)))


if __name__ == "__main__":
    main(sys.argv)
