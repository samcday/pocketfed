#!/usr/bin/env python3
"""Turn a piglit shader_test into something shader-db's run accepts:
explicit #version from [require] GLSL >= X.YZ, and a real vertex shader in
place of [vertex shader passthrough]."""
import re, sys
for p in sys.argv[1:]:
    s = open(p).read()
    m = re.search(r'GLSL >= (\d)\.(\d\d)', s)
    ver = m.group(1) + m.group(2) if m else '110'
    out = []
    for sec in re.split(r'(?m)^(?=\[)', s):
        head = sec.split('\n', 1)[0]
        if head.startswith('[vertex shader passthrough]'):
            out.append('[vertex shader]\n#version %s\nin vec4 piglit_vertex;\nvoid main() { gl_Position = piglit_vertex; }\n\n' % ver)
        elif head.startswith('[vertex shader]') or head.startswith('[fragment shader]'):
            h, body = sec.split('\n', 1)
            out.append(h + '\n#version %s\n' % ver + body)
        elif head.startswith('[test]') or head.startswith('[require]'):
            out.append(sec if head.startswith('[require]') else '')
        else:
            out.append(sec)
    q = p.replace('.shader_test', '.sdb.shader_test')
    open(q, 'w').write(''.join(out))
    print(q)
