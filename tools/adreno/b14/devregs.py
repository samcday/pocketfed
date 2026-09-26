#!/usr/bin/env python3
"""Print selected CP/HLSQ registers from msm devcoredumps (a3xx)."""
import re, sys
NAMES = {0x01d5:'CP_MEQ?/0x1d5',0x01d6:'CP_MEQ_THRESHOLDS',0x01d7:'CP_CSQ_AVAIL',0x01d8:'CP_STQ_AVAIL',0x01d9:'CP_MEQ_AVAIL',
 0x01fc:'CP_DEBUG',0x01fd:'CP_CSQ_RB_STAT',0x01fe:'CP_CSQ_IB1_STAT',0x01ff:'CP_CSQ_IB2_STAT',0x01f7:'CP_ME_STATUS',
 0x0440:'CP_?440',0x0443:'CP_STQ_ST_STAT',0x0445:'CP_?445',0x044d:'CP_ST_BASE',0x044e:'CP_ST_BUFSZ',0x044f:'CP_MEQ_STAT',
 0x0452:'CP_?452',0x0454:'CP_?454',0x0455:'CP_?455',0x0456:'CP_?456',0x0457:'CP_?457',
 0x0458:'CP_IB1_BASE',0x0459:'CP_IB1_BUFSZ',0x045a:'CP_IB2_BASE',0x045b:'CP_IB2_BUFSZ',
 0x047c:'CP_?47c',0x047f:'CP_STAT',0x0578:'CP_SCRATCH0',0x057d:'CP_SCRATCH5',0x057e:'CP_SCRATCH6',0x057f:'CP_SCRATCH7'}
for path in sys.argv[1:]:
    text = open(path, errors='replace').read()
    regs = {}
    for m in re.finditer(r'-\s*\{\s*offset:\s*(0x[0-9a-fA-F]+),\s*value:\s*(0x[0-9a-fA-F]+)\s*\}', text):
        regs[int(m.group(1),16)//4] = int(m.group(2),16)
    hdr = {k: re.search(k + r':\s*(\S+)', text) for k in ('rbbm-status','rptr','wptr','last-fence','retired-fence')}
    print('==', path.split('/')[-1], ' '.join(f'{k}={v.group(1)}' for k,v in hdr.items() if v))
    for off in sorted(NAMES):
        if off in regs:
            print(f'  {off:#06x} {NAMES[off]:<18} {regs[off]:#010x}')
