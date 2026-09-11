#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Check the packaged artwork's mobile fit and rendering-critical invariants."""
import configparser
import sys
from pathlib import Path
from PIL import Image

assets = Path(sys.argv[1])
theme = configparser.ConfigParser()
theme.read(Path(__file__).with_name("fedora-mobile.plymouth"))
assert theme["Plymouth Theme"]["ModuleName"] == "two-step"
frames = sorted(assets.glob("throbber-*.png"))
assert len(frames) == 60
assert len({Image.open(frame).tobytes() for frame in frames}) == 60
for frame in frames:
    image = Image.open(frame)
    assert image.mode == "RGBA" and image.size == (240, 206)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getbbox() is not None
entry, lock, bullet = (Image.open(assets / (name + ".png"))
                       for name in ("entry", "lock", "bullet"))
assert entry.width + lock.width <= 280  # Fits 320 logical px with margins.
assert entry.height >= 40 and bullet.width <= entry.width / 10
assert min(entry.getpixel((110, 24))[:3]) > 230  # Built-in black text is readable.
assert max(bullet.getpixel((7, 7))[:3]) < 80
for mode in ("boot-up", "shutdown", "reboot", "updates", "system-upgrade",
             "firmware-upgrade", "system-reset"):
    assert not theme[mode].getboolean("UseEndAnimation")
    assert not theme[mode].getboolean("SuppressMessages", fallback=False)
for mode in ("updates", "system-upgrade", "firmware-upgrade", "system-reset"):
    assert theme[mode].getboolean("UseProgressBar")
assert sum(path.stat().st_size for path in assets.glob("*.png")) < 1_000_000
print("PASS: 60 unique frames, transparent assets, readable prompt, mobile fit, modes, <1 MB PNG payload")
