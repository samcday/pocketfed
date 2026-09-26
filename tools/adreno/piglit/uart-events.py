#!/usr/bin/env python3
"""Per-run GPU error summary from the host-side UART log.

A run spans from its '== LABEL arm=' banner to the matching
'== deqp-runner rc=' / '== piglit rc=' line (or the next banner / boot
marker if the board reset). Kernel lines are deduplicated by their
[uptime] stamp, since a306_gpu_log re-prints dmesg to the console.
usage: uart-events.py UART_LOG [LABEL-regex]
"""
import re, sys
log = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace').replace('\r', '')
flt = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
lines = log.split('\n')
banner = re.compile(r'== (\S+) arm=(\S+) ')
endre = re.compile(r'== (deqp-runner|piglit) rc=(\d+)')
kstamp = re.compile(r'\[\s*(\d+\.\d+)\]')
runs, cur = [], None
for ln in lines:
    m = banner.search(ln)
    if m or ln.startswith('=== B') or 'U-Boot 20' in ln:
        if cur:
            cur['end'] = cur.get('end') or ('RESET/next-boot' if ('U-Boot' in ln or ln.startswith('=== B')) else 'interrupted')
            runs.append(cur); cur = None
        if m:
            cur = {'label': m.group(1), 'arm': m.group(2), 'k': {}, 'end': None, 'first': None}
        continue
    if cur is None:
        continue
    e = endre.search(ln)
    if e:
        cur['end'] = 'rc=' + e.group(2)
        runs.append(cur); cur = None
        continue
    k = kstamp.search(ln)
    if k and ('msm' in ln or 'smmu' in ln.lower() or 'adreno' in ln):
        cur['k'].setdefault(k.group(1), ln.strip())
if cur:
    cur['end'] = cur['end'] or 'running/cut'
    runs.append(cur)
for r in runs:
    if flt and not flt.search(r['label']):
        continue
    ks = r['k'].values()
    hc = [l for l in ks if 'hangcheck detected' in l]
    fault = [l for l in ks if re.search(r'fault', l, re.I)]
    off = [re.sub(r'.*offending task: ', '', l) for l in ks if 'offending task' in l]
    print(f"{r['label']:32s} arm={r['arm']:4s} end={r['end']:16s} hangchecks={len(hc)} faults={len(fault)}")
    from collections import Counter
    for cmd, n in Counter(off).most_common():
        print(f"    {n}x {cmd}")
    for l in fault[:3]:
        print('    FAULT', l[:200])
