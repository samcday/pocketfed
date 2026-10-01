#!/usr/bin/env python3
"""Push a file to the DB410c guest over the UART console.

Chunked base64 with a per-chunk SHA256 readback and automatic retry.
The guest console is put into raw mode (-icanon -echo) only for the
duration of each chunk's `head -c` receiver, so the interactive shell
is undisturbed either side of it.
"""
import argparse, base64, hashlib, json, os, re, sys, time, uuid

ap = argparse.ArgumentParser()
ap.add_argument('--fifo', required=True)
ap.add_argument('--log', required=True)
ap.add_argument('--src', required=True)
ap.add_argument('--dst', required=True, help='absolute path on the guest')
ap.add_argument('--chunk', type=int, default=192 * 1024, help='source bytes per chunk')
ap.add_argument('--block', type=int, default=256)
ap.add_argument('--delay', type=float, default=0.035)
ap.add_argument('--retries', type=int, default=3)
a = ap.parse_args()

def logsize():
    return os.path.getsize(a.log) if os.path.exists(a.log) else 0

def put(obj):
    with open(a.fifo, 'w') as f:
        f.write(json.dumps(obj) + '\n')

def send_cmd(cmd, pace=0.002):
    put({'send': cmd + '\n', 'pace': pace})

def wait(start, pattern, timeout):
    pat = re.compile(pattern.encode())
    end = time.time() + timeout
    while time.time() < end:
        with open(a.log, 'rb') as f:
            f.seek(start)
            data = f.read()
        m = pat.search(data)
        if m:
            return data, m
        time.sleep(0.15)
    with open(a.log, 'rb') as f:
        f.seek(start)
        data = f.read()
    return data, None

def run(cmd, timeout=60):
    mk = 'MK' + uuid.uuid4().hex[:8]
    st = logsize()
    send_cmd('%s; echo "__%s""%s__rc=$?"' % (cmd, mk[:2], mk[2:]))
    data, m = wait(st, '__%s__rc=(-?\\d+)' % mk, timeout)
    if not m:
        raise RuntimeError('timeout waiting for %s\n%s' % (mk, data[-800:]))
    return data[:m.start()].decode('utf-8', 'replace')

raw = open(a.src, 'rb').read()
full_sha = hashlib.sha256(raw).hexdigest()
nchunks = (len(raw) + a.chunk - 1) // a.chunk
tmpdir = '/run/xfer.%s' % uuid.uuid4().hex[:6]
print('src=%s %d bytes sha256=%s -> guest %s (%d chunks via %s)'
      % (a.src, len(raw), full_sha, a.dst, nchunks, tmpdir), flush=True)
run('mkdir -p %s && rm -f %s/part.*' % (tmpdir, tmpdir))

t0 = time.time()
for i in range(nchunks):
    piece = raw[i * a.chunk:(i + 1) * a.chunk]
    b64 = base64.b64encode(piece)
    wrapped = b'\n'.join(b64[j:j + 120] for j in range(0, len(b64), 120)) + b'\n'
    want = hashlib.sha256(wrapped).hexdigest()
    part = '%s/part.%03d' % (tmpdir, i)
    for attempt in range(1, a.retries + 1):
        st = logsize()
        send_cmd("printf 'RDY""TOK\\n'; stty -icanon -echo min 1 time 0; "
                 "head -c %d > %s; stty icanon echo; sha256sum %s"
                 % (len(wrapped), part, part))
        _, m = wait(st, 'RDYTOK', 20)
        if not m:
            raise RuntimeError('chunk %d: receiver never signalled ready' % i)
        time.sleep(0.4)
        st2 = logsize()
        put({'b64': base64.b64encode(wrapped).decode(),
             'block': a.block, 'delay': a.delay})
        expect = len(wrapped) * a.delay / a.block + 30
        data, m = wait(st2, '([0-9a-f]{64})\\s+%s' % re.escape(part), expect)
        got = m.group(1).decode() if m else None
        if got == want:
            done = (i + 1) * a.chunk
            el = time.time() - t0
            print('chunk %d/%d ok (%d B, %.1f s elapsed, %.0f B/s)'
                  % (i + 1, nchunks, len(piece), el, min(done, len(raw)) / el), flush=True)
            break
        print('chunk %d attempt %d MISMATCH want=%s got=%s' % (i, attempt, want[:16], got),
              flush=True)
        if attempt == a.retries:
            raise RuntimeError('chunk %d failed after %d attempts' % (i, a.retries))
    else:
        raise RuntimeError('chunk %d exhausted' % i)

out = run('cat %s/part.* | base64 -d > %s && rm -rf %s && sha256sum %s'
          % (tmpdir, a.dst, tmpdir, a.dst), timeout=180)
print(out.strip()[-200:])
print('EXPECTED sha256 %s' % full_sha)
print('MATCH' if full_sha in out else 'SHA MISMATCH')
