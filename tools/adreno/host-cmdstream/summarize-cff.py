#!/usr/bin/env python3
"""Collapse a cffdump decode into one diffable line per register write and per
CP_LOAD_STATE / CP_EVENT_WRITE packet, with iovas replaced by placeholders so
two arms of the same workload differ only where the driver actually differs.

usage: summarize-cff.py <cffdump-output.txt>
"""
import re, sys
path = sys.argv[1]
lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
out=[]; i=0
while i < len(lines):
    raw = lines[i]; l = raw.strip()
    m = re.match(r'opcode: (\w+) \((\w+)\) \((\d+) dwords\)', l)
    if m:
        op=m.group(1)
        if op=='CP_LOAD_STATE':
            out.append('PKT %-14s %s %s' % (op, lines[i+1].strip(), re.sub(r'EXT_SRC_ADDR = 0x[0-9a-f]+','EXT_SRC_ADDR = <bo>',lines[i+2].strip())))
        elif op=='CP_EVENT_WRITE':
            out.append('PKT %-14s %s' % (op, lines[i+1].strip()))
        else:
            out.append('PKT %s' % op)
        i+=1; continue
    m = re.match(r'write ([A-Z][A-Z0-9_\[\]\.x]*) \(', l)
    if m:
        j=i+1; vals=[]
        while j < len(lines):
            s=lines[j].strip()
            if re.match(r'^[A-Z][A-Z0-9_\[\]\.x]*:', s):
                vals.append(re.sub(r'0x[0-9a-f]{6,}','<addr>',s)); j+=1
            elif s.startswith('NEEDS WFI'):
                j+=1
            else: break
        out.append('REG ' + ' ; '.join(vals))
        i=j; continue
    i+=1
print('\n'.join(out))
