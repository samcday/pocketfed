#!/usr/bin/env python3
"""Run real dequeue/callback functions against empty and successful V4L2 reads."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path,help='Megapixels source root')
parser.add_argument('--cc',default='cc')
args=parser.parse_args()
camera=(args.source/'src/camera.c').read_text()
pipeline=(args.source/'src/pipeline.c').read_text()
dequeue=camera[camera.index('bool\nmp_camera_capture_buffer('):camera.index('bool\nmp_camera_release_buffer(')]
callback=pipeline[pipeline.index('static bool\non_capture('):pipeline.index('// Not thread safe',pipeline.index('static bool\non_capture('))]
with tempfile.TemporaryDirectory(prefix='megapixels-empty-dequeue-') as directory:
    work=Path(directory)
    (work/'dequeue.c').write_text(dequeue)
    (work/'callback.c').write_text(callback)
    exe=work/'test'
    subprocess.run([args.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-I',str(work),str(Path(__file__).with_name('empty-dequeue-fixture.c')),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,timeout=10)
