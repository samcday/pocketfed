#!/usr/bin/env python3
"""Report JPEG geometry/EXIF and decode the public camera-target QR payload.

Requires Pillow and either zbarimg or OpenCV (cv2). Exits 0 for a matching QR,
1 for a valid JPEG without the expected QR, or 2 for an input/dependency error.
This cannot certify focus, readable text, exposure, colour, or orientation.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PAYLOAD = "PocketFed sam-sargo camera test 2026-09-10"
ORIENTATIONS = {
    1: "normal", 2: "mirrored horizontally", 3: "rotated 180 degrees",
    4: "mirrored vertically", 5: "transposed", 6: "rotated 90 degrees clockwise",
    7: "transverse", 8: "rotated 90 degrees counterclockwise",
}


def decode(image, backend):
    if backend in ("auto", "zbar") and shutil.which("zbarimg"):
        with tempfile.TemporaryDirectory(prefix="pocketfed-qr-") as directory:
            path = Path(directory) / "oriented.png"
            image.save(path)
            result = subprocess.run(
                ["zbarimg", "--quiet", "--raw", "--set", "*.enable=0", "--set", "qrcode.enable=1", str(path)],
                capture_output=True, text=True, timeout=90,
            )
        if result.returncode not in (0, 4):
            raise RuntimeError(f"zbarimg failed ({result.returncode}): {result.stderr.strip()}")
        return "zbar", result.stdout.splitlines()
    if backend == "zbar":
        raise RuntimeError("zbarimg is not installed")
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError("install zbarimg (Fedora package: zbar) or Python opencv-python-headless") from error
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Native resolution first; large camera images can decode better when reduced.
    candidates = [gray]
    for longest in (2400, 1600):
        if max(gray.shape) > longest:
            scale = longest / max(gray.shape)
            candidates.append(cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))
    payloads = set()
    for candidate in candidates:
        detector = cv2.QRCodeDetector()
        found, values, _corners, _straight = detector.detectAndDecodeMulti(candidate)
        if found:
            payloads.update(value for value in values if value)
        value, _corners, _straight = detector.detectAndDecode(candidate)
        if value:
            payloads.add(value)
        if PAYLOAD in payloads:
            break
    return "opencv", sorted(payloads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jpeg", type=Path)
    parser.add_argument("--backend", choices=("auto", "zbar", "opencv"), default="auto")
    args = parser.parse_args()
    try:
        from PIL import Image, ImageOps

        path = args.jpeg.resolve(strict=True)
        with Image.open(path) as original:
            if original.format != "JPEG":
                raise ValueError(f"expected JPEG, found {original.format}")
            original.load()
            orientation = original.getexif().get(274)
            report = {
                "file": str(path), "bytes": path.stat().st_size, "format": original.format,
                "stored_dimensions": list(original.size), "exif_orientation": orientation,
                "exif_orientation_description": ORIENTATIONS.get(orientation, "absent" if orientation is None else "unknown"),
            }
            oriented = ImageOps.exif_transpose(original).convert("RGB")
        backend, payloads = decode(oriented, args.backend)
        report.update({
            "display_dimensions": list(oriented.size), "qr_backend": backend,
            "expected_qr_payload": PAYLOAD, "decoded_qr_payloads": payloads,
            "qr_matches": PAYLOAD in payloads,
            "requires_visual_review": ["printed text readability", "focus", "exposure", "colour", "upright and not mirrored"],
        })
        print(json.dumps(report, indent=2))
        return 0 if report["qr_matches"] else 1
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
