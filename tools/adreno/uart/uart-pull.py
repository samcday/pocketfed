#!/usr/bin/env python3
"""Pull a file from the DB410c guest over the UART console (xz + base64)."""
import argparse, base64, hashlib, json, os, re, sys, time, uuid

ap = argparse.ArgumentParser()
ap.add_argument('--fifo', required=True)
ap.add_argument('--log', required=True)
ap.add_argument('--src', required=True, help='guest path')
ap.add_argument('--dst', required=True, help='host path (xz-compressed payload is decompressed)')
ap.add_argument('--timeout', type=float, default=600)
a = ap.parse_args()

def logsize():
    return os.path.getsize(a.log) if os.path.exists(a.log) else 0

mk = uuid.uuid4().hex[:8]
st = logsize()
cmd = ("echo \"B%sEG:%s:$(xz -9 -c %s | sha256sum | cut -d' ' -f1)\"; "
       "xz -9 -c %s | base64 -w 120; echo \"B%sEND\"\n"
       % ('64', mk, a.src, a.src, '64'))
with open(a.fifo, 'w') as f:
    f.write(json.dumps({'send': cmd, 'pace': 0.002}) + '\n')

pat = re.compile(b'B64EG:' + mk.encode() + b':([0-9a-f]{64})(.*?)B64END', re.S)
end = time.time() + a.timeout
m = None
while time.time() < end:
    with open(a.log, 'rb') as f:
        f.seek(st)
        data = f.read()
    m = pat.search(data)
    if m:
        break
    time.sleep(0.5)
if not m:
    sys.exit('timeout: no complete payload')

want = m.group(1).decode()
body = re.sub(rb'[^A-Za-z0-9+/=]', b'', m.group(2))
blob = base64.b64decode(body)
got = hashlib.sha256(blob).hexdigest()
print('xz payload %d bytes sha256=%s expected=%s %s'
      % (len(blob), got[:16], want[:16], 'OK' if got == want else 'MISMATCH'))
if got != want:
    sys.exit(1)
import lzma
raw = lzma.decompress(blob)
open(a.dst, 'wb').write(raw)
print('wrote %s (%d bytes) sha256=%s' % (a.dst, len(raw), hashlib.sha256(raw).hexdigest()))
