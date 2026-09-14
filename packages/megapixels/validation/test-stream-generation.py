#!/usr/bin/env python3
"""Replay delayed buffer returns across stop/start using the production callbacks."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--cc', default='cc')
args = parser.parse_args()
source = (args.source / 'src/io_pipeline.c').read_text()
generation = 'static void\nstop_capture(void)' in source
release = source[source.index('static void\nrelease_buffer('):source.index('static pid_t focus_continuous_task')]
if generation:
    stop = source[source.index('static void\nstop_capture(void)'):source.index('typedef struct invoke_set_control')]
    # Every production mode switch and camera replacement must invalidate returns.
    assert source.count('mp_camera_stop_capture(mpcamera);') == 1
    assert source.count('stop_capture();') == 3
else:
    stop = 'static void stop_capture(void) { mp_camera_stop_capture(mpcamera); }\n'
with tempfile.TemporaryDirectory(prefix='megapixels-stream-generation-') as directory:
    work = Path(directory)
    (work / 'stop.c').write_text(stop)
    (work / 'release.c').write_text(release)
    executable = work / 'test'
    subprocess.run([args.cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-DGENERATION=' + str(int(generation)),
                    '-I', str(work), str(Path(__file__).with_name('stream-generation-fixture.c')),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)
