#!/usr/bin/env python3
"""Exercise actual stop blocks with fake trace reads and recorded teardown.

No root, tracefs, kernel probe or device access. Signals hit a real process
blocked reading a FIFO; the mocked teardown records invocation and result.
"""
from pathlib import Path
import os, signal, subprocess, tempfile, time
root=Path.cwd()
for name in ('trace-recovery-returns.sh','trace-vbif-halt.sh','trace-uninitialized-idle-all3.sh'):
 text=(root/'tools/adreno'/name).read_text()
 block=text[text.index('result=0\n# Preserve the interrupt'):]
 for case in ('success','int','term','term-cleanup-fails'):
  with tempfile.TemporaryDirectory(prefix='a3stop-test-') as directory:
   d=Path(directory); state=d/'state';state.mkdir();instance=d/'instance';instance.mkdir()
   (instance/'trace_marker').write_text('');(instance/'tracing_on').write_text('1')
   if case=='success': (instance/'trace').write_text('test trace\n')
   else: os.mkfifo(instance/'trace')
   pre='''set -euo pipefail
state=$1
instance=$2
cleanup_rc=$3
profile() { printf 'test 1 0\\n'; }
teardown() { printf 'called\\n' >> "$state/teardown-calls"; return "$cleanup_rc"; }
'''
   script=d/'stop.sh';script.write_text(pre+block)
   rc=1 if case.endswith('fails') else 0
   proc=subprocess.Popen(['bash',str(script),str(state),str(instance),str(rc)],start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   if case!='success':
    deadline=time.monotonic()+5
    while not (state/'trace.txt').exists() and time.monotonic()<deadline:
     if proc.poll() is not None: raise AssertionError(proc.communicate())
     time.sleep(.01)
    assert (state/'trace.txt').exists(), 'stop never began trace read'
    time.sleep(.05)
    os.killpg(proc.pid, signal.SIGINT if case=='int' else signal.SIGTERM)
   stdout,stderr=proc.communicate(timeout=5)
   expected=0 if case=='success' else 130 if case=='int' else 143
   assert proc.returncode==expected,(name,case,proc.returncode,stdout,stderr)
   assert (state/'teardown-calls').read_text()=='called\n',(name,case)
   expected_status='stopped' if case=='success' else 'cleanup-incomplete' if rc else 'stopped-incomplete'
   assert (state/'status').read_text().strip()==expected_status,(name,case)
   print(name,case,'PASS',expected,expected_status)
