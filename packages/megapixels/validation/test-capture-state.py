#!/usr/bin/env python3
"""Exercise the real burst start and IO-to-process state publication functions."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--cc', default='cc')
args = parser.parse_args()
io = (args.source / 'src/io_pipeline.c').read_text()
proc = (args.source / 'src/process_pipeline.c').read_text()
functions = {
    'publish.c': io[io.index('static void\nupdate_process_pipeline('):io.index('static void\nfocus(')],
    'capture-io.c': io[io.index('static void\ncapture('):io.index('void\nmp_io_pipeline_capture(')],
    'capture-process.c': proc[proc.index('static void\ncapture('):proc.index('void\nmp_process_pipeline_capture(')],
}
with tempfile.TemporaryDirectory(prefix='megapixels-capture-state-') as directory:
    work = Path(directory)
    for name, source in functions.items():
        (work / name).write_text(source)
    executable = work / 'test'
    subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-I', str(work),
                    str(Path(__file__).with_name('capture-state-fixture.c')),
                    '-lm', '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
