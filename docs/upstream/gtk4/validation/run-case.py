#!/usr/bin/python3
"""Exit 0 for preserved preedit, 1 for the reset bug, 125 for invalid trials.

Run under dbus-run-session. Uses a private headless Phoc and disposable C
GtkTextView; the input method sends only synthetic test text.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--library-dir', required=True)
parser.add_argument('--dependency-dir', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--word', default='hello')
parser.add_argument('--action', choices=['reset', 'layout', 'cursor', 'focus'])
args = parser.parse_args()
base = Path(__file__).resolve().parent
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=False)
runtime = output / 'runtime'
runtime.mkdir(mode=0o700)
config = output / 'phoc.ini'
config.write_text('')
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY='ime-bisect',
           WLR_BACKENDS='headless', WLR_HEADLESS_OUTPUTS='1', WLR_RENDERER='pixman',
           GDK_BACKEND='wayland', GTK_IM_MODULE='wayland', GSK_RENDERER='cairo',
           GTK_A11Y='test', GSETTINGS_BACKEND='memory',
           GDK_WAYLAND_DISABLE='wp_cursor_shape_manager_v1')
env.pop('LD_LIBRARY_PATH', None)
env.pop('LD_PRELOAD', None)
processes = []
result = {'classification': 'invalid', 'exit_code': 125, 'word': args.word, 'action': args.action}
if args.action:
    env['IME_TEST_ACTION'] = args.action

def start(argv, name, child_env):
    with (output / name).open('w') as stream:
        process = subprocess.Popen(argv, cwd=output, env=child_env,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    processes.append(process)
    return process

try:
    compositor = start(['/usr/bin/phoc', '--no-xwayland', '--socket=ime-bisect',
                        '-C', str(config)], 'phoc.log', env)
    deadline = time.monotonic() + 6
    while not (runtime / 'ime-bisect').exists():
        if compositor.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError('Headless Phoc failed to start')
        time.sleep(.05)
    probe_env = dict(env, LD_LIBRARY_PATH=args.library_dir + ':' + args.dependency_dir,
                     WAYLAND_DEBUG='client')
    library = (Path(args.library_dir) / 'libgtk-4.so.1').resolve(strict=True)
    result['library'] = str(library)
    result['disabled_wayland_globals'] = env['GDK_WAYLAND_DISABLE']
    result['gtk_a11y'] = env['GTK_A11Y']
    result['library_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    version_code = "import ctypes;g=ctypes.CDLL('libgtk-4.so.1');print('.'.join(str(getattr(g,'gtk_get_'+s+'_version')()) for s in ['major','minor','micro']))"
    result['gtk_version'] = subprocess.check_output(
        ['/usr/bin/python3', '-c', version_code], env=probe_env, text=True).strip()
    driver = start(['/usr/bin/python3', str(base / 'ime-driver.py'), args.word],
                   'driver.log', env)
    probe = start([str(base / 'gtk4-preedit')], 'probe.log', probe_env)
    driver.wait(timeout=6)
    time.sleep(.1)
    if driver.returncode != 0 or probe.poll() is not None:
        raise RuntimeError('Input method or probe did not complete a valid trial')
    maps = Path(f'/proc/{probe.pid}/maps').read_text()
    result['mapped_library'] = sorted({line.split()[-1] for line in maps.splitlines()
                                       if 'libgtk-4.so' in line})
    if result['mapped_library'] != [str(library)]:
        raise RuntimeError('Probe loaded an unexpected GTK library')
    observation = json.loads((output / 'driver.log').read_text())
    state = observation['state']
    result['observation'] = observation
    probe_log = (output / 'probe.log').read_text()
    if not state['sent'] or (not state['active'] and args.action != 'focus') or ('PREEDIT: ' + args.word) not in probe_log:
        raise RuntimeError('The expected preedit was not observed')
    if args.action == 'cursor' and (state.get('cursor') != 0 or not any(e.get('cursor') == 7 for e in observation['events'])):
        raise RuntimeError('Logical cursor did not move from the end of prefix to its start')
    if args.action and ('ACTION: ' + args.action) not in probe_log:
        raise RuntimeError('Requested action did not execute')
    if args.action == 'focus' and not state['active'] and not state['committed'] and 'BUFFER:' not in probe_log and 'PREEDIT: \n' in probe_log:
        result.update(classification='focus-cleared', exit_code=0)
    elif state['committed'] and not state['reset'] and state['text'] == args.word + ' ' and ('BUFFER: ' + args.word + ' ') in probe_log:
        result.update(classification='good', exit_code=0)
    elif state['reset'] and not state['committed'] and state['text'] == ('prefix ' if args.action == 'cursor' else '') and 'BUFFER:' not in probe_log:
        result.update(classification='bad', exit_code=1)
    else:
        raise RuntimeError('Unexpected preedit/commit result')
except Exception as exc:
    result['error'] = str(exc)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
sys.exit(result['exit_code'])
