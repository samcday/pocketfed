#!/usr/bin/env python3
"""Extract the 'Native code for ...' blocks from an IR3_SHADER_DEBUG=disasm
dump (MESA: info: prefixed), keyed by stage+blake3, for diffing."""
import re, sys
def blocks(path):
    out, cur, key = {}, None, None
    for ln in open(path, errors='replace'):
        ln = ln.replace('MESA: info: ', '').rstrip('\n')
        m = re.match(r'Native code for unnamed (\w+) shader \S+ with blake3 (\w+)', ln)
        if m:
            key = m.group(1) + ':' + m.group(2)[:12]; cur = out.setdefault(key, []); continue
        if cur is not None:
            if ln.startswith('shader:') or ln.startswith('---') or ln.startswith('dump nir'):
                cur = None; continue
            if ln.strip() and not ln.startswith(';') and not ln.startswith('Thread '):
                cur.append(ln.strip())
    return out
if __name__ == '__main__':
    a, b = blocks(sys.argv[1]), blocks(sys.argv[2])
    same = diff = 0
    for k in sorted(set(a) | set(b)):
        if a.get(k) == b.get(k): same += 1
        else:
            diff += 1
            print(f'  DIFF {k}: {len(a.get(k, []))} vs {len(b.get(k, []))} instrs; mgen {sum("mgen" in l for l in a.get(k, []))} -> {sum("mgen" in l for l in b.get(k, []))}')
    print(f'  {same} shaders identical, {diff} differ')
