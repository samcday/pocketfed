#!/usr/bin/env python3
"""Read-only numerical audit; does not emit or install any camera profile.

Usage: numeric-audit.py /path/to/Megapixels-source
"""
import argparse, ctypes, json, pathlib, re, subprocess, tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=pathlib.Path, help='Megapixels source root')
args = parser.parse_args()
base = args.source
text = (base / 'src/matrix.h').read_text()
def matrix(name):
    body = re.search(r'static float ' + name + r'\[.*?\] = \{(.*?)\};', text, re.S)[1]
    body = re.sub(r'//[^\n]*', '', body)
    return [float(x.strip().rstrip('f')) for x in body.split(',') if x.strip()]
A, S, T = [matrix(x) for x in ('XYZD50_to_D65','XYZD65_to_sRGB','sRGB_to_XYZD65')]
F32 = ctypes.c_float * 9
with tempfile.TemporaryDirectory() as tmp:
    so = str(pathlib.Path(tmp)/'matrix.so')
    subprocess.run(['cc','-shared','-fPIC',str(base/'src/matrix.c'),'-o',so],check=True)
    lib = ctypes.CDLL(so)
    def mul(a,b):
        out=F32(); lib.multiply_matrices(F32(*a),F32(*b),out); return list(out)
    def inv(m):
        # Use independent Gauss-Jordan: source invert_matrix has its own determinant typo.
        rows=[m[i*3:i*3+3]+[float(i==j) for j in range(3)] for i in range(3)]
        for i in range(3):
            pivot=max(range(i,3), key=lambda j:abs(rows[j][i])); rows[i],rows[pivot]=rows[pivot],rows[i]
            d=rows[i][i]; rows[i]=[v/d for v in rows[i]]
            for j in range(3):
                if i!=j:
                    d=rows[j][i]; rows[j]=[x-d*y for x,y in zip(rows[j],rows[i])]
        return [v for row in rows for v in row[3:]]
    def mv(m,v):return [sum(m[i*3+j]*v[j] for j in range(3)) for i in range(3)]
    def roundv(v):return [round(x,6) for x in v]
    # D50-referred synthetic sRGB camera: expected composed calibration is identity.
    # This is an algebra test fixture, NOT an IMX363 calibration.
    F=mul(inv(A),inv(S))
    examples=[]
    for red,blue in ((1,1),(2,1.5)):
        W=[red,0,0,0,1,0,0,0,blue]
        current=mul(mul(mul(W,F),A),S)
        correct=mul(mul(mul(S,A),F),W)
        for pixel in ((.5,.5,.5),(.25,.5,.5/blue),(.1,.4,.2)):
            examples.append(dict(gains=[red,1,blue],raw_pixel=pixel,current=roundv(mv(current,pixel)),correct=roundv(mv(correct,pixel))))
    fallback=mul(mul(T,A),S)
    CM1=[1.0598,-.5058,-.1606,-.9956,1.9269,.0401,.0642,-.2328,1.2123]
    report={
      'fixture':'synthetic D50 sRGB camera, F=inv(A)*inv(S); not a generated profile',
      'production_multiply_source':str(base/'src/matrix.c'),
      'fixture_F_times_one':roundv(mv(F,[1,1,1])),
      'composition_examples':examples,
      'fallback_gray_half_rgb':roundv(mv(fallback,[.5,.5,.5])),
      'AAA_current_CM1_times_rendered_gray_128':roundv(mv(CM1,[128,128,128])),
      'AAA_correct_for_neutral_rendered_gray': [128,128,128],
      'AsShotNeutral_for_gains_2_1_1p5':{'written':[2,1,1.5],'required':[.5,1,2/3]},
      'neutral_raw_0p25_0p5_0p3333_after_current_DNG_gains':[.125,.5,2/9],
      'neutral_raw_0p25_0p5_0p3333_after_correct_DNG_gains':[.5,.5,.5]
    }
    print(json.dumps(report,indent=2))
