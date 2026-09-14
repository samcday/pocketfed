#!/usr/bin/env python3
"""Test production flip negotiation across Bayer layouts and ioctl failures."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='patched src/pipeline.c')
parser.add_argument('--cc', default='cc')
args = parser.parse_args()
source = args.source.read_text()
functions = source[source.index('static int\nbayer_phase('):source.index('unsigned int\nlibmegapixels_select_mode(')]
with tempfile.TemporaryDirectory(prefix='libmegapixels-bayer-order-') as directory:
    work = Path(directory)
    (work / 'bayer-order.c').write_text(functions)
    executable = work / 'test'
    subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(work), str(Path(__file__).with_name('bayer-order-fixture.c')),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
