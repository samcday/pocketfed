#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Finish a deferred trail check from captured PNGs, without phone dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path, help="Directory copied from run-swipe.py --defer-pixel-check")
args = parser.parse_args()
source = args.output / "result.json"
result = json.loads(source.read_text())
assert result["case"] == "swipe" and result["status"] == "pending-pixel-check", "Expected a successful functional run with deferred pixels"
reference = Image.open(args.output / "trail-reference.png").convert("RGB")
assert reference.size == (360, 720), "Unexpected output dimensions"
reference = reference.crop((0, 520, 360, 720))
energy = {}
hashes = {}
for name in ["released", "decaying", "cleared", "reference"]:
    path = args.output / f"trail-{name}.png"
    hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    frame = Image.open(path).convert("RGB")
    assert frame.size == (360, 720), "Unexpected frame dimensions"
    if name != "reference":
        energy[name] = sum(ImageStat.Stat(ImageChops.difference(reference, frame.crop((0, 520, 360, 720)))).sum)
assert energy["released"] > energy["decaying"] > energy["cleared"], "Trail must visibly decay then disappear"
assert energy["cleared"] == 0, "Trail animation should finish"
result.update(status="passed", trail_pixel_check="verified from captured PNGs on host",
              trail_difference_energy=energy, trail_frame_sha256=hashes,
              source_result_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
(args.output / "result-verified.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"status": "passed", "trail_difference_energy": energy}))
