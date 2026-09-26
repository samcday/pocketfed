#!/usr/bin/env python3
"""Compare eglretrace snapshot PNGs against a reference: exact-pixel stats."""
import hashlib
import sys

import numpy as np
from PIL import Image

ref_path, *paths = sys.argv[1:]
ref = np.asarray(Image.open(ref_path).convert('RGB'), dtype=np.int16)
print(f'reference {ref_path} {ref.shape[1]}x{ref.shape[0]} '
      f'sha256={hashlib.sha256(open(ref_path, "rb").read()).hexdigest()[:16]}')
for p in paths:
    img = np.asarray(Image.open(p).convert('RGB'), dtype=np.int16)
    sha = hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16]
    if img.shape != ref.shape:
        print(f'{p}: shape {img.shape} != {ref.shape}')
        continue
    diff = np.abs(img - ref)
    exact = np.all(diff == 0, axis=2)
    print(f'{p}: sha256={sha} exact={exact.mean() * 100:.4f}% '
          f'max_delta={int(diff.max())} differing_pixels={int((~exact).sum())}')
