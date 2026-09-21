#!/usr/bin/env python3
"""Exercise the actual fastboop consumer without USB, mounting, or root privileges."""
import ctypes
import ctypes.util
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


BINARY = Path(os.environ.get("LIVEBOOT_BINARY", "target/debug/pocketfed-liveboot")).resolve()


class HostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.env = dict(os.environ, FASTBOOP_STAGE0_PATH="/nonexistent-stage0",
                        FASTBOOP_SCHEMA_PATH=str(self.path / "devpro"),
                        XDG_CONFIG_HOME=str(self.path / "config"),
                        XDG_CACHE_HOME=str(self.path / "cache"), RUST_LOG="warn")
        self.root = self.path / "root.ext4"
        subprocess.run(["mkfs.ext4", "-q", "-F", "-b", "4096", str(self.root), "4096"],
                       check=True, capture_output=True)
        self.root_hash = hashlib.sha256(self.root.read_bytes()).digest()
        kernel = bytearray(b"synthetic arm64 kernel\0" * 4000)
        kernel[:2] = b"MZ"
        struct.pack_into("<Q", kernel, 16, len(kernel))
        kernel[56:60] = b"ARM\x64"
        self.kernel = bytes(kernel)
        (self.path / "Image").write_bytes(self.kernel)
        self.initrd = gzip.compress(b"opaque supplied initrd; never execute stage0", mtime=0)
        (self.path / "initrd").write_bytes(self.initrd)
        subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", str(self.path / "board.dtb")],
                       input=b'/dts-v1/; / { compatible = "pocketfed,test"; };',
                       check=True, capture_output=True)
        self.profile = {
            "id": "test-board", "display_name": "Synthetic test board",
            "devicetree_name": "test/board",
            "match": [{"fastboot": {"vid": 0x18d1, "pid": 0xd00d}}],
            "probe": [{"fastboot.getvar": "product", "equals": "test-board"}],
            "boot": {"fastboot_boot": {"android_bootimg": {
                "header_version": 2, "page_size": 4096, "base": 0x80000000,
                "kernel_offset": 0x80000, "ramdisk_offset": 0x1000000,
                "second_offset": 0, "tags_offset": 0x100, "dtb_offset": 0x2000000,
                "kernel": {"encoding": "image.gz"},
                "cmdline_append": "console=ttyTEST0",
            }}}
        }
        (self.path / "device.yaml").write_text(json.dumps(self.profile))
        (self.path / "cmdline").write_text("ostree=/ostree/boot.1/test/0 rootfstype=ext4 rd.smoo.cow.size=512M")

    def cli(self, *args, success=True, env=None):
        result = subprocess.run([str(BINARY), *map(str, args)], env=env or self.env,
                                text=True, capture_output=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def bundle(self, *extra, success=True):
        return self.cli("bundle", "--root-image", self.root, "--kernel", self.path / "Image",
                        "--initrd", self.path / "initrd", "--dtb", self.path / "board.dtb",
                        "--device-profile", self.path / "device.yaml", "--serial", "TEST-SERIAL",
                        "--cmdline-file", self.path / "cmdline", "--out", self.path / "bundle",
                        *extra, success=success)

    def test_separate_inputs_reach_fastboop_payload(self):
        self.bundle()
        out = self.path / "boot.img"
        self.cli("image", self.path / "bundle", "--output", out)
        image = out.read_bytes()
        u32 = lambda offset: struct.unpack_from("<I", image, offset)[0]
        self.assertEqual(image[:8], b"ANDROID!")
        self.assertEqual(u32(40), 2)
        self.assertEqual(u32(36), 4096)
        self.assertEqual(u32(12), 0x80080000)
        self.assertEqual(u32(20), 0x81000000)
        self.assertEqual(struct.unpack_from("<Q", image, 1652)[0], 0x82000000)
        kernel_len, initrd_len, dtb_len = u32(8), u32(16), u32(1648)
        self.assertEqual(gzip.decompress(image[4096:4096 + kernel_len]), self.kernel)
        initrd_start = 4096 + ((kernel_len + 4095) // 4096) * 4096
        self.assertEqual(image[initrd_start:initrd_start + initrd_len], self.initrd)
        dtb_start = initrd_start + ((initrd_len + 4095) // 4096) * 4096
        self.assertEqual(image[dtb_start:dtb_start + dtb_len], (self.path / "board.dtb").read_bytes())
        cmdline = (image[64:576].split(b"\0")[0] + image[608:1632].split(b"\0")[0]).decode()
        args = cmdline.split()
        for arg in ["console=ttyTEST0", "root=/dev/smoo-root", "rd.smoo=1", "rd.smoo.cow=1",
                    "rd.smoo.force_root=1", "rd.smoo.mimic_fastboot=0",
                    "rd.smoo.cow.size=512M", "ostree=/ostree/boot.1/test/0"]:
            self.assertEqual(args.count(arg), 1, cmdline)
        export = [arg for arg in args if arg.startswith("rd.smoo.root=")]
        self.assertEqual(len(export), 1)
        self.assertTrue(export[0].split("=")[1].isdigit())
        self.assertEqual(hashlib.sha256(self.root.read_bytes()).digest(), self.root_hash)
        device = (self.path / "bundle/device.yaml").read_text()
        self.assertIn("fastboot.getvar: serialno", device)
        self.assertIn("equals: TEST-SERIAL", device)

    def test_existing_outputs_are_not_overwritten(self):
        self.bundle()
        self.bundle(success=False)
        self.cli("image", self.path / "bundle", "--output", self.root, success=False)
        link = self.path / "link.img"
        link.symlink_to(self.root)
        self.cli("image", self.path / "bundle", "--output", link, success=False)
        self.assertEqual(hashlib.sha256(self.root.read_bytes()).digest(), self.root_hash)

    def test_conflicting_contract_is_rejected_before_creating_bundle(self):
        for arg in ["root=LABEL=pfroot", "rd.smoo.cow=0", "rd.smoo.root=7"]:
            with self.subTest(arg=arg):
                (self.path / "cmdline").write_text(arg)
                result = self.bundle(success=False)
                self.assertIn("invalid image command line", result.stderr)
                self.assertFalse((self.path / "bundle").exists())

    def test_shim_targets_stop_before_image_or_usb(self):
        self.profile["devicetree_name"] = "qcom/sdm670-google-sargo"
        (self.path / "device.yaml").write_text(json.dumps(self.profile))
        self.bundle()
        out = self.path / "boot.img"
        for args in [("image", "--output", out), ("boot", "--wait", "0")]:
            result = self.cli(args[0], self.path / "bundle", *args[1:], success=False)
            self.assertIn("requires shim composition", result.stderr)
        self.assertFalse(out.exists())

    def test_profile_traversal_is_rejected(self):
        self.profile["devicetree_name"] = "../escaped"
        (self.path / "device.yaml").write_text(json.dumps(self.profile))
        result = self.bundle(success=False)
        self.assertIn("relative path", result.stderr)
        self.assertFalse((self.path / "bundle").exists())

    def test_supplied_shim_reaches_fastboop_ablx_composition(self):
        shim = bytearray(b"\x5a" * 128)
        struct.pack_into("<Q", shim, 16, len(shim))
        shim[56:60] = b"ARM\x64"
        (self.path / "shim").write_bytes(shim)
        self.profile["devicetree_name"] = "qcom/sdm670-google-sargo"
        geometry = self.profile["boot"]["fastboot_boot"]["android_bootimg"]
        geometry["base"] = 0
        geometry["ramdisk_offset"] = 0x04000000
        (self.path / "device.yaml").write_text(json.dumps(self.profile))
        self.bundle("--shim", self.path / "shim")
        self.assertEqual((self.path / "bundle/shim.bin").read_bytes(), shim)
        out = self.path / "boot.img"
        self.cli("image", self.path / "bundle", "--output", out)
        image = out.read_bytes()
        u32 = lambda offset: struct.unpack_from("<I", image, offset)[0]
        self.assertEqual(u32(20), 0x04000000)
        self.assertEqual(gzip.decompress(image[4096:4096 + u32(8)]), shim)
        start = 4096 + ((u32(8) + 4095) // 4096) * 4096
        ramdisk = image[start:start + u32(16)]
        self.assertEqual(ramdisk[:8], b"ABLXRD1\0")
        self.assertEqual(struct.unpack_from("<II", ramdisk, 8), (72, 2))
        field = lambda offset: struct.unpack_from("<Q", ramdisk, offset)[0]
        self.assertEqual(field(32), len(self.kernel))
        self.assertEqual(field(56), len(self.initrd))
        self.assertEqual(ramdisk[field(48):field(48) + field(56)], self.initrd)
        # Independent decoder: system liblz4, rather than fastboop's Rust encoder.
        lz4 = ctypes.CDLL(ctypes.util.find_library("lz4"))
        decompress = lz4.LZ4_decompress_safe
        decompress.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        decompress.restype = ctypes.c_int
        decoded = ctypes.create_string_buffer(field(32))
        compressed = ramdisk[field(16):field(16) + field(24)]
        self.assertEqual(decompress(compressed, decoded, len(compressed), len(decoded)), len(self.kernel))
        self.assertEqual(decoded.raw, self.kernel)
        cmdline = (image[64:576].split(b"\0")[0] + image[608:1632].split(b"\0")[0]).decode()
        self.assertTrue(cmdline.startswith("<S> console=ttyTEST0 "), cmdline)
        self.assertTrue(cmdline.endswith(" <E>"), cmdline)
        self.assertEqual(cmdline.count("<S>"), 1)
        self.assertEqual(cmdline.count("<E>"), 1)
        self.assertIn("root=/dev/smoo-root", cmdline)
        self.assertIn("rd.smoo.cow=1", cmdline)
        self.assertEqual(hashlib.sha256(self.root.read_bytes()).digest(), self.root_hash)

    def test_invalid_shim_does_not_produce_an_image(self):
        (self.path / "shim").write_bytes(b"not a raw ARM64 shim")
        self.bundle("--requires-shim", "--shim", self.path / "shim")
        out = self.path / "boot.img"
        result = self.cli("image", self.path / "bundle", "--output", out, success=False)
        self.assertIn("prepare supplied initrd", result.stderr)
        self.assertFalse(out.exists())

    def test_local_profile_cannot_override_serial_probe(self):
        self.bundle()
        directory = self.path / "devpro"
        directory.mkdir()
        metadata = json.loads((self.path / "bundle/bundle.json").read_text())
        self.profile["id"] = metadata["device_profile"]
        (directory / "override.yaml").write_text(json.dumps(self.profile))
        result = self.cli("image", self.path / "bundle", "--output", self.path / "boot.img", success=False)
        self.assertIn("shadows this bundle", result.stderr)

    def test_failed_preparation_removes_reserved_output(self):
        self.bundle()
        (self.path / "bundle/boot-artifacts.ext4").unlink()
        out = self.path / "boot.img"
        self.cli("image", self.path / "bundle", "--output", out, success=False)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
