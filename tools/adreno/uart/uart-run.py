#!/usr/bin/env python3
"""Send a shell command to the board and wait for its completion marker."""
import argparse, base64, json, os, re, sys, time, uuid

p = argparse.ArgumentParser()
p.add_argument('--fifo', required=True)
p.add_argument('--log', required=True)
p.add_argument('--timeout', type=float, default=30.0)
p.add_argument('--pace', type=float, default=0.002)
p.add_argument('--raw-b64', help='send raw base64-decoded bytes, no marker wrap')
p.add_argument('--wait-for', help='regex to wait for instead of a marker')
p.add_argument('--no-cmd', action='store_true', help='only wait, send nothing')
p.add_argument('cmd', nargs='?', default='')
a = p.parse_args()

start = os.path.getsize(a.log) if os.path.exists(a.log) else 0
mk = 'MK' + uuid.uuid4().hex[:8]
if a.no_cmd:
    payload = None
elif a.raw_b64:
    payload = json.dumps({'b64': a.raw_b64, 'pace': a.pace})
else:
    # split the marker so the shell's own echo of the command never matches
    wrapped = '%s; __rc=$?; echo "__%s""%s__rc=$__rc"\n' % (a.cmd, mk[:2], mk[2:])
    payload = json.dumps({'send': wrapped, 'pace': a.pace})

pat = re.compile(a.wait_for.encode()) if a.wait_for else re.compile(
    ('__%s__rc=(-?\\d+)' % mk).encode())

if payload is not None:
    with open(a.fifo, 'w') as f:
        f.write(payload + '\n')

deadline = time.time() + a.timeout
data = b''
hit = None
while time.time() < deadline:
    with open(a.log, 'rb') as f:
        f.seek(start)
        data = f.read()
    hit = pat.search(data)
    if hit:
        break
    time.sleep(0.15)

out = data[:hit.start()] if hit else data
txt = out.decode('utf-8', 'replace').replace('\r\n', '\n')
sys.stdout.write(txt)
if hit:
    sys.stdout.write('\n[marker %s]\n' % hit.group(0).decode('utf-8', 'replace'))
    sys.exit(0)
sys.stdout.write('\n[TIMEOUT after %.1fs, no marker]\n' % a.timeout)
sys.exit(2)
