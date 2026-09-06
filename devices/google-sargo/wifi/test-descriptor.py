#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline regression tests; no phone, network, root, or firmware blob needed."""

import lzma
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


HERE = Path(__file__).resolve().parent
HELPER = runpy.run_path(str(HERE / "generate-descriptor.py"))
BASELINE = bytes.fromhex(
    "51 43 41 2d 41 54 48 31 30 4b 00 77 01 00 00 00 "
    "04 00 00 00 a4 e4 be 5b 02 00 00 00 03 00 00 00 "
    "40 00 0c 77 05 00 00 00 04 00 00 00 04 00 00 00 "
    "06 00 00 00 04 00 00 00 03 00 00 00"
)


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pocketfed-wcn3990-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.raw = self.directory / "firmware-5.bin"
        self.compressed = self.directory / "firmware-5.bin.xz"

    def test_exactly_the_tested_bit_changes(self):
        corrected = HELPER["descriptor"]()
        self.assertEqual(HELPER["descriptor"](mfp=False), BASELINE)
        self.assertEqual(len(corrected), 60)
        self.assertEqual([(i, a ^ b) for i, (a, b) in enumerate(zip(BASELINE, corrected))
                          if a != b], [(33, 0x10)])
        # Match the kernel/fwencoder convention, not zlib's default seed/xor.
        self.assertEqual(zlib.crc32(BASELINE, 0xffffffff) ^ 0xffffffff, 0xb3d4b790)
        self.assertEqual(zlib.crc32(corrected, 0xffffffff) ^ 0xffffffff, 0xeda01cc5)

    def test_only_metadata_tlvs(self):
        data = HELPER["descriptor"]()
        offset = 12
        elements = {}
        while offset < len(data):
            kind, length = struct.unpack_from("<II", data, offset)
            offset += 8
            self.assertNotIn(kind, elements)
            elements[kind] = data[offset:offset + length]
            offset += (length + 3) & ~3
        self.assertEqual(offset, len(data))
        self.assertEqual(elements, {
            1: struct.pack("<I", 1539237028),
            2: bytes.fromhex("40 10 0c"),
            5: struct.pack("<I", 4),
            6: struct.pack("<I", 3),
        })

    def test_compressed_input_is_preserved_and_other_files_untouched(self):
        compressed = lzma.compress(BASELINE)
        self.compressed.write_bytes(compressed)
        unrelated = self.directory / "wlanmdsp.mbn"
        unrelated.write_bytes(b"not an actual executable blob")
        HELPER["install"](self.directory)
        self.assertEqual(self.raw.read_bytes(), HELPER["descriptor"]())
        self.assertEqual(self.raw.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.compressed.read_bytes(), compressed)
        self.assertEqual(unrelated.read_bytes(), b"not an actual executable blob")

    def test_uncompressed_input_and_repeat_install(self):
        self.raw.write_bytes(BASELINE)
        for _ in range(2):
            HELPER["install"](self.directory)
            self.assertEqual(self.raw.read_bytes(), HELPER["descriptor"]())

    def test_upstream_already_fixed(self):
        self.compressed.write_bytes(lzma.compress(HELPER["descriptor"]()))
        HELPER["install"](self.directory)
        self.assertEqual(self.raw.read_bytes(), HELPER["descriptor"]())

    def test_missing_input(self):
        with self.assertRaisesRegex(ValueError, "No packaged"):
            HELPER["install"](self.directory)
        self.assertFalse(self.raw.exists())

    def test_changed_metadata_is_not_overwritten(self):
        for changed in (BASELINE[:-1], BASELINE + b"new TLV", b"different firmware"):
            self.raw.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "Unreviewed"):
                HELPER["install"](self.directory)
            self.assertEqual(self.raw.read_bytes(), changed)

    def test_raw_override_cannot_hide_changed_compressed_package(self):
        self.raw.write_bytes(HELPER["descriptor"]())
        self.compressed.write_bytes(lzma.compress(BASELINE + b"new TLV"))
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            HELPER["install"](self.directory)
        self.assertEqual(self.raw.read_bytes(), HELPER["descriptor"]())

    def test_invalid_compression(self):
        self.compressed.write_bytes(b"invalid xz")
        with self.assertRaises(lzma.LZMAError):
            HELPER["install"](self.directory)
        self.assertFalse(self.raw.exists())

    def test_symlink_rejected(self):
        other = self.directory / "other"
        other.write_bytes(BASELINE)
        self.raw.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "symlink"):
            HELPER["install"](self.directory)
        self.assertEqual(other.read_bytes(), BASELINE)

    def test_dangling_symlink_rejected(self):
        self.raw.symlink_to(self.directory / "missing")
        self.compressed.write_bytes(lzma.compress(BASELINE))
        with self.assertRaisesRegex(ValueError, "symlink"):
            HELPER["install"](self.directory)
        self.assertFalse((self.directory / "missing").exists())

    def test_build_command(self):
        command = [sys.executable, str(HERE / "generate-descriptor.py"), str(self.directory)]
        missing = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("No packaged", missing.stderr)
        self.compressed.write_bytes(lzma.compress(BASELINE))
        subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(self.raw.read_bytes(), HELPER["descriptor"]())


if __name__ == "__main__":
    unittest.main()
