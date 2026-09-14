#!/usr/bin/env python3
"""Check the actual DNG neutral export against known white-balance responses."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='patched src/process_pipeline.c')
parser.add_argument('--cc', default='cc')
args = parser.parse_args()
source = args.source.read_text()
start = source.index('libdng_set_neutral(&dng,')
statement = source[start:source.index(');', start)+2]
with tempfile.TemporaryDirectory(prefix='megapixels-dng-neutral-') as directory:
    work = Path(directory)
    (work / 'neutral-export.c').write_text(statement+'\n')
    executable = work / 'test'
    subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(work), str(Path(__file__).with_name('dng-neutral-fixture.c')),
                    '-lm', '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
