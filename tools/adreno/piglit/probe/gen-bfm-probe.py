#!/usr/bin/env python3
"""Generate shader_tests that make ir3 emit MGEN.B (nir bfm) with uniform
operands and write the raw 32-bit result into the framebuffer as four
unorm8 bytes (little-endian).  Expected values follow NIR's bfm semantics,
  ((1u << (bits & 31)) - 1u) << (offset & 31),
so every failing probe's "Observed" line is the hardware's actual value.
  mask:  (1u << bits) - 1u              -> bfm(bits, 0)   [nir_opt_algebraic]
  shift: ((1u << bits) - 1u) << offset  -> bfm(bits, offset) if folded
"""
import sys, os
out = sys.argv[1] if len(sys.argv) > 1 else '.'
def enc(v):
    return ' '.join('%.6f' % (((v >> (8*i)) & 0xff) / 255.0) for i in range(4))
def nir_bfm(bits, off):
    return ((((1 << (bits & 31)) - 1) & 0xffffffff) << (off & 31)) & 0xffffffff
HEAD = """[require]
GLSL >= 1.30
GL_MESA_shader_integer_functions

[vertex shader passthrough]

[fragment shader]
#extension GL_MESA_shader_integer_functions : enable
out vec4 color;
uniform uint bits;
uniform uint offset;
void main()
{
	uint v = %s;
	color = vec4(float(v & 0xffu), float((v >> 8u) & 0xffu),
	             float((v >> 16u) & 0xffu), float((v >> 24u) & 0xffu)) / 255.0;
}

[test]
tolerance 0.002 0.002 0.002 0.002

"""
bits_cases = [0, 1, 4, 7, 8, 15, 16, 24, 31, 32, 33, 40, 63, 64, 65, 96, 127, 128, 255, 256, 1023, 0x7fffffff, 0xffffffff]
def write(name, expr, cases):
    with open(os.path.join(out, name), 'w') as f:
        f.write(HEAD % expr)
        for b, o in cases:
            f.write('# bits=%d offset=%d -> nir 0x%08x\n' % (b, o, nir_bfm(b, o)))
            f.write('uniform uint bits %d\nuniform uint offset %d\n' % (b, o))
            f.write('draw rect -1 -1 2 2\nprobe all rgba %s\n\n' % enc(nir_bfm(b, o)))
write('bfm-mask.shader_test', '(1u << bits) - 1u', [(b, 0) for b in bits_cases])
write('bfm-shift.shader_test', '((1u << bits) - 1u) << offset',
      [(4,0),(4,16),(4,28),(4,29),(4,31),(4,32),(4,33),(4,36),(0,0),(0,16),(0,31),(0,32),
       (32,0),(32,4),(33,4),(31,1),(31,2),(16,16),(16,17),(16,20),(1,31),(1,32),(33,33),(255,255),(64,64)])
# plain shift for reference: does the a3xx shl mask its count to 5 bits?
with open(os.path.join(out, 'shl-ref.shader_test'), 'w') as f:
    f.write(HEAD % '1u << bits')
    for b in bits_cases:
        v = (1 << (b & 31)) & 0xffffffff
        f.write('# bits=%d -> nir 0x%08x\nuniform uint bits %d\nuniform uint offset 0\ndraw rect -1 -1 2 2\nprobe all rgba %s\n\n' % (b, v, b, enc(v)))
print('wrote', os.listdir(out))
