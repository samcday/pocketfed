#!/usr/bin/env python3
"""Host-only checks for the Fedora RPM to kboop bundle producer; no device access."""

import gzip
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "fedora_kernel_bundle", Path(__file__).with_name("fedora-kernel-bundle.py"))
bundler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundler)


def kernel_image(release, size=512):
    image = bytearray(size)
    image[56:60] = b"ARM\x64"
    struct.pack_into("<Q", image, 16, len(image))
    banner = ("Linux version " + release + " (builder@host)\0").encode()
    image[128:128 + len(banner)] = banner
    return bytes(image)


def zboot(payload, compression):
    header = bytearray(64)
    header[:2] = b"MZ"
    header[4:8] = b"zimg"
    struct.pack_into("<II", header, 8, 64, len(payload))
    header[24:24 + len(compression)] = compression
    return bytes(header) + payload


class DecodeTests(unittest.TestCase):
    def test_zboot_gzip_decodes_to_a_valid_gzip_image(self):
        release = "6.1.0-zboot-test"
        image = kernel_image(release)
        encoded = bundler.encode_image_gz(zboot(gzip.compress(image, mtime=0), b"gzip"))
        self.assertEqual(encoded[:2], b"\x1f\x8b")
        decoded = gzip.decompress(encoded)
        self.assertEqual(decoded, image)
        self.assertEqual(decoded[56:60], b"ARM\x64")
        self.assertIn(("Linux version " + release + " (").encode(), decoded)

    def test_plain_gzip_and_reused_prepare_fixture_decoder(self):
        image = kernel_image("6.2.0-plain")
        self.assertEqual(gzip.decompress(bundler.encode_image_gz(gzip.compress(image, mtime=0))), image)

    def test_rejects_non_arm64_payload(self):
        with self.assertRaises(bundler.prepare_fixture.FixtureError):
            bundler.encode_image_gz(gzip.compress(b"other architecture", mtime=0))


class EarlyModuleTests(unittest.TestCase):
    def test_classifies_present_builtin_and_absent_in_order(self):
        names = ["present_mod", "built-in-mod", "absent_mod", "missing"]
        report = bundler.classify_early_modules(names, {"present_mod"}, {"built_in_mod"})
        self.assertEqual(report, [("present_mod", "present"), ("built-in-mod", "builtin"),
                                  ("absent_mod", "absent"), ("missing", "absent")])

    def test_reads_dep_and_builtin_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "modules.dep").write_text(
                "kernel/drivers/foo/bar-baz.ko.xz: kernel/lib/qux.ko.xz\n"
                "kernel/lib/qux.ko.xz:\n")
            (root / "modules.builtin").write_text("kernel/drivers/foo/inline.ko\n")
            installed = bundler.installed_module_names(root / "modules.dep")
            builtin = bundler.builtin_module_names(root / "modules.builtin")
            self.assertEqual(installed, {"bar_baz", "qux"})
            self.assertEqual(builtin, {"inline"})


class CommonHelperTests(unittest.TestCase):
    def test_early_modules_parses_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "initrd.conf"
            config.write_text(
                'force_drivers+=" \\\n    alpha \\\n    beta"\n'
                'add_drivers+=" \\\n    beta \\\n    gamma"\n')
            self.assertEqual(bundler.hwe_common.early_modules(config),
                             ["alpha", "beta", "gamma"])

    def test_early_module_report_uses_the_given_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "modules.dep").write_text("kernel/alpha.ko.xz:\n")
            (root / "modules.builtin").write_text("kernel/beta.ko\n")
            config = root / "initrd.conf"
            config.write_text('force_drivers+="alpha beta gamma"\n')
            self.assertEqual(bundler.early_module_report(root, config),
                             [("alpha", "present"), ("beta", "builtin"), ("gamma", "absent")])


class OrderTests(unittest.TestCase):
    def test_translates_installed_modules_order_to_build_style_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "modules.order"
            source.write_text(
                "kernel/arch/arm64/crypto/ghash-ce.ko\n"
                "kernel/drivers/gpu/drm/amd/amdgpu/../display/amdgpu_dm/tests/amdgpu_dm_test.ko\n"
                "kernel/kernel/sysctl-test.ko\n")
            destination = Path(temporary) / "normalized.order"
            self.assertEqual(bundler.synthesize_modules_order(source, destination), 3)
            self.assertEqual(destination.read_text().splitlines(), [
                "arch/arm64/crypto/ghash-ce.o",
                "drivers/gpu/drm/amd/display/amdgpu_dm/tests/amdgpu_dm_test.o",
                "kernel/sysctl-test.o",
            ])

    def test_rejects_duplicate_or_malformed_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "modules.order"
            destination = Path(temporary) / "normalized.order"
            source.write_text("kernel/a.ko\nkernel/a.ko\n")
            with self.assertRaisesRegex(bundler.BundleError, "duplicate"):
                bundler.synthesize_modules_order(source, destination)
            source.write_text("drivers/a.o\n")
            with self.assertRaisesRegex(bundler.BundleError, "unexpected"):
                bundler.synthesize_modules_order(source, destination)


class RelocateTests(unittest.TestCase):
    def test_moves_internal_tests_under_kernel_and_strips_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "6.1-test"
            (root / "kernel/crypto").mkdir(parents=True)
            (root / "kernel/crypto/regular.ko.xz").write_bytes(b"regular")
            (root / "internal/crypto").mkdir(parents=True)
            (root / "internal/crypto/raid6test.ko.xz").write_bytes(b"internal")
            (root / "dtb/qcom").mkdir(parents=True)
            (root / "vmlinuz").write_bytes(b"kernel")
            (root / "config").write_bytes(b"config")
            (root / "System.map").write_bytes(b"map")
            (root / "build").symlink_to("/usr/src/kernels/6.1-test")
            bundler.relocate_internal(root)
            bundler.strip_kernel_artifacts(root)
            self.assertTrue((root / "kernel/crypto/raid6test.ko.xz").is_file())
            self.assertFalse((root / "internal").exists())
            for name in ("vmlinuz", "config", "System.map", "build", "dtb"):
                self.assertFalse((root / name).exists())

    def test_refuses_internal_module_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "6.1-test"
            (root / "kernel/fs").mkdir(parents=True)
            (root / "kernel/fs/same.ko.xz").write_bytes(b"regular")
            (root / "internal/fs").mkdir(parents=True)
            (root / "internal/fs/same.ko.xz").write_bytes(b"internal")
            with self.assertRaisesRegex(bundler.BundleError, "collides"):
                bundler.relocate_internal(root)


class ManifestTests(unittest.TestCase):
    def test_bundle_manifest_shape_and_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "dtb/qcom").mkdir(parents=True)
            (output / "Image.gz").write_bytes(b"gzip image")
            (output / "dtb/qcom/x.dtb").write_bytes(b"dtb")
            release = "6.1.0-test.aarch64"
            module_files = {f"lib/modules/{release}/modules.dep": "0" * 64,
                            f"lib/modules/{release}/modules.builtin": "1" * 64}
            manifest = bundler.bundle_manifest(release, output, "dtb/qcom/x.dtb", module_files)
            self.assertEqual(set(manifest), {
                "schema_version", "release", "image", "dtb", "modules_install", "module_files"})
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["release"], release)
            self.assertEqual(manifest["image"],
                             {"path": "Image.gz", "sha256": bundler.build_kernel.sha256(output / "Image.gz")})
            self.assertEqual(manifest["dtb"],
                             {"path": "dtb/qcom/x.dtb", "sha256": bundler.build_kernel.sha256(output / "dtb/qcom/x.dtb")})
            self.assertEqual(manifest["modules_install"], "modules")
            self.assertEqual(manifest["module_files"], module_files)
            target = output / "bundle.json"
            bundler.build_kernel.write_json(target, manifest)
            self.assertEqual(json.loads(target.read_text()), manifest)

    def test_parses_fedora_rpm_filename_without_rpm(self):
        record = bundler.parse_rpm_filename(
            Path("kernel-core-7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64.rpm"))
        self.assertEqual(record["name"], "kernel-core")
        self.assertEqual(record["version"], "7.3.0")
        self.assertEqual(record["release"], "0.rc3.260914g704340f1cd0d.32.fc46")
        self.assertEqual(record["arch"], "aarch64")


if __name__ == "__main__":
    unittest.main()
