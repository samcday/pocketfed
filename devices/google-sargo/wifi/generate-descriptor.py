#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate Sargo's metadata-only ath10k API5 descriptor during image build.

See README.md for the ath10k-fwencoder equivalent and hardware test scope.
No executable firmware or calibration data is read, modified, or generated.
"""

import argparse
import lzma
from pathlib import Path
import struct


def descriptor(*, mfp=True):
    # Public ath10k API constants from core.h/hw.h, not firmware instructions.
    features = (1 << 6) | (1 << 18) | (1 << 19)  # wowlan, mgmt-tx-by-ref, non-bmi
    if mfp:
        features |= 1 << 12  # ATH10K_FW_FEATURE_MFP_SUPPORT

    def tlv(kind, payload):
        return struct.pack("<II", kind, len(payload)) + payload + b"w" * (-len(payload) % 4)

    return (
        b"QCA-ATH10K\0w"
        # Retain the packaged metadata timestamp, not the runtime blob version.
        + tlv(1, struct.pack("<I", 1539237028))
        + tlv(2, features.to_bytes(3, "little"))
        + tlv(5, struct.pack("<I", 4))  # WMI TLV
        + tlv(6, struct.pack("<I", 3))  # HTT TLV
    )


def install(directory):
    target = directory / "firmware-5.bin"
    # Fedora ships .xz today. Also check an uncompressed file if present:
    # the kernel prefers it, and it must not hide an unreviewed package update.
    inputs = [path for path in (target, target.with_suffix(".bin.xz"))
              if path.exists() or path.is_symlink()]
    if not inputs:
        raise ValueError(f"No packaged WCN3990 API5 descriptor in {directory}")
    for path in inputs:
        if path.is_symlink():
            raise ValueError(f"Unexpected descriptor symlink: {path}")
        data = path.read_bytes()
        if path.suffix == ".xz":
            data = lzma.decompress(data)
        if data not in (descriptor(mfp=False), descriptor()):
            raise ValueError(f"Unreviewed WCN3990 descriptor: {path}; revisit the Sargo override")

    # Only the generated descriptor is installed. Keep the packaged .xz intact.
    # Same-directory uncompressed firmware takes precedence over compressed.
    target.write_bytes(descriptor())
    target.chmod(0o644)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="ath10k/WCN3990/hw1.0 directory")
    args = parser.parse_args()
    try:
        install(args.directory)
    except (OSError, ValueError, lzma.LZMAError) as error:
        parser.exit(1, f"{error}\n")
