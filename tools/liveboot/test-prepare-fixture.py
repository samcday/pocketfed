#!/usr/bin/env python3
"""Host-only fixture exporter regression tests; no Podman or device access."""

import gzip
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location("prepare_fixture", Path(__file__).with_name("prepare-fixture.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def boot_image(shim=b"a production ABLX shim"):
    page = 4096
    kernel = gzip.compress(shim, mtime=0)
    header = bytearray(page)
    header[:8] = b"ANDROID!"
    for offset, value in ((8, len(kernel)), (16, 1), (36, page), (40, 2), (1644, 1660), (1648, 1)):
        struct.pack_into("<I", header, offset, value)
    return bytes(header) + kernel.ljust(page, b"\0") + b"r".ljust(page, b"\0") + b"d".ljust(page, b"\0")


def kernel_image():
    image = bytearray(128)
    image[56:60] = b"ARM\x64"
    struct.pack_into("<Q", image, 16, len(image))
    return bytes(image)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.output = self.base / "output"
        self.output.mkdir()
        self.source = self.root / "usr/lib/modules/6.19.8-test.aarch64"
        self.source.mkdir(parents=True)
        (self.source / "kernel/net").mkdir(parents=True)
        (self.source / "kernel/net/example.ko.zst").write_bytes(b"a compressed module")
        (self.source / "dtb/qcom").mkdir(parents=True)
        (self.source / "dtb/qcom/sargo.dtb").write_bytes(b"device tree")
        (self.source / "vmlinuz").write_bytes(gzip.compress(kernel_image(), mtime=0))
        (self.source / "config").write_text("CONFIG_ARM64=y\nCONFIG_SECURITY_SELINUX=y\n")
        (self.source / "aboot.img").write_bytes(boot_image())
        (self.source / "build").symlink_to("/unavailable/build/host")
        (self.source / "source").symlink_to("/unavailable/source")

    def test_extracts_complete_versioned_bundle_and_original_shim(self):
        original = fixture.tree_inventory(self.root)
        metadata = fixture.extract_kernel(self.root, self.output, "qcom/sargo.dtb")
        bundle = self.output / "kernel-bundle"
        manifest = json.loads((bundle / "bundle.json").read_text())
        self.assertEqual(manifest["release"], "6.19.8-test.aarch64")
        actual = fixture.tree_inventory(bundle / "modules")
        self.assertEqual(manifest["module_files"], {k: v["sha256"] for k, v in actual.items()})
        self.assertEqual(metadata["omitted_module_symlinks"], ["build", "source"])
        self.assertEqual((self.output / "production-ablx-shim.bin").read_bytes(), b"a production ABLX shim")
        self.assertEqual(gzip.decompress((self.output / "production-ablx-shim.gz").read_bytes()), b"a production ABLX shim")
        self.assertEqual((bundle / "kernel.config").read_bytes(), (self.source / "config").read_bytes())
        self.assertEqual(fixture.tree_inventory(self.root), original)

    def test_rejects_unexpected_module_symlink(self):
        (self.source / "kernel/escape").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(fixture.FixtureError, "unexpected symlink"):
            fixture.extract_kernel(self.root, self.output, "qcom/sargo.dtb")

    def test_rejects_multiple_kernel_releases(self):
        (self.source.parent / "second-release").mkdir()
        with self.assertRaisesRegex(fixture.FixtureError, "exactly one"):
            fixture.extract_kernel(self.root, self.output, "qcom/sargo.dtb")

    def test_rejects_symlink_in_dtb_path(self):
        (self.source / "dtb/external").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(fixture.FixtureError, "symlink"):
            fixture.extract_kernel(self.root, self.output, "external/sargo.dtb")

    def test_rejects_trailing_or_truncated_android_payloads(self):
        aboot = self.source / "aboot.img"
        for data in (boot_image() + b"extra", boot_image()[:-1]):
            aboot.write_bytes(data)
            with self.assertRaisesRegex(fixture.FixtureError, "truncated|trailing"):
                fixture.extract_shim(aboot, self.output / "shim.gz", self.output / "shim.bin")

    def test_rejects_invalid_gzip_shim(self):
        data = bytearray(boot_image())
        data[4096] = 0
        aboot = self.source / "aboot.img"
        aboot.write_bytes(data)
        with self.assertRaisesRegex(fixture.FixtureError, "gzip"):
                fixture.extract_shim(aboot, self.output / "shim.gz", self.output / "shim.bin")

    def test_decodes_efi_zboot_gzip_with_explicit_payload_bounds(self):
        payload = gzip.compress(kernel_image(), mtime=0)
        header = bytearray(64)
        header[:2] = b"MZ"
        header[4:8] = b"zimg"
        struct.pack_into("<II", header, 8, 64, len(payload))
        header[24:28] = b"gzip"
        self.assertEqual(fixture.canonical_kernel(bytes(header) + payload), kernel_image())
        with self.assertRaisesRegex(fixture.FixtureError, "bounds"):
            fixture.canonical_kernel(bytes(header) + payload[:-1])

    def test_rejects_non_arm64_kernel_payload(self):
        with self.assertRaisesRegex(fixture.FixtureError, "arm64"):
            fixture.canonical_kernel(gzip.compress(b"some other architecture", mtime=0))

    def test_overlay_replaces_symlink_without_following_it(self):
        overlay = self.base / "overlay"
        (overlay / "etc/systemd/system").mkdir(parents=True)
        (overlay / "etc/systemd/system/example.service").symlink_to("/dev/null")
        (self.root / "etc/systemd/system").mkdir(parents=True)
        outside = self.base / "untouched"
        outside.write_text("still here")
        (self.root / "etc/systemd/system/example.service").symlink_to(outside)
        with mock.patch.object(fixture.os, "chown"):
            fixture.apply_overlay(self.root, overlay)
        self.assertEqual((self.root / "etc/systemd/system/example.service").readlink(), Path("/dev/null"))
        self.assertEqual(outside.read_text(), "still here")

    def test_overlay_rejects_symlink_parent(self):
        overlay = self.base / "overlay"
        (overlay / "etc/systemd").mkdir(parents=True)
        (self.root / "etc").symlink_to(self.base)
        with self.assertRaisesRegex(fixture.FixtureError, "conflicts|symlink"):
            fixture.apply_overlay(self.root, overlay)

    def test_reuse_verifies_fingerprint_and_exact_artifact_inventory(self):
        (self.output / "rootfs.erofs").write_bytes(b"erofs")
        manifest = {"schema_version": 1, "input_fingerprint": "one", "artifacts": fixture.tree_inventory(self.output)}
        (self.output / "fixture.json").write_bytes(fixture.encoded(manifest))
        fixture.verify_reuse(self.output, "one")
        with self.assertRaisesRegex(fixture.FixtureError, "exact inputs"):
            fixture.verify_reuse(self.output, "two")
        (self.output / "rootfs.erofs").write_bytes(b"corrupted")
        with self.assertRaisesRegex(fixture.FixtureError, "changed"):
            fixture.verify_reuse(self.output, "one")
        (self.output / "rootfs.erofs").write_bytes(b"erofs")
        (self.output / "surprise").write_text("extra")
        with self.assertRaisesRegex(fixture.FixtureError, "unexpected"):
            fixture.verify_reuse(self.output, "one")

    def test_rejects_mutable_ref_and_digest_mismatch(self):
        with self.assertRaisesRegex(fixture.FixtureError, "pinned"):
            fixture.image_identity("ghcr.io/example:latest")
        with mock.patch.object(fixture, "run", return_value='[{"Digest":"sha256:other"}]'):
            with self.assertRaisesRegex(fixture.FixtureError, "does not match"):
                fixture.image_identity("ghcr.io/example@sha256:" + "a" * 64)

    def test_full_local_image_id_is_pinned_without_registry_access(self):
        image_id = "sha256:" + "c" * 64
        info = {"Id": image_id, "Architecture": "arm64", "Os": "linux"}
        with mock.patch.object(fixture, "run", return_value=json.dumps([info])) as inspect:
            result = fixture.image_identity(image_id)
        self.assertEqual(result["id"], image_id)
        self.assertEqual(result["reference"], image_id)
        self.assertEqual(inspect.call_args.args[0], ["podman", "image", "inspect", image_id])
        with mock.patch.object(fixture, "run", return_value=json.dumps([info])):
            with self.assertRaisesRegex(fixture.FixtureError, "ID does not match"):
                fixture.image_identity("sha256:" + "d" * 64)

    def test_rejects_path_traversal(self):
        for value in ("/absolute", "../escape", "qcom/../../escape", ".", ""):
            with self.subTest(value=value), self.assertRaises(fixture.FixtureError):
                fixture.relative_path(value)


class FlatRootTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("etc", "var", "usr/lib/systemd", "sysroot/ostree/repo/objects"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.systemd = self.root / "usr/lib/systemd/systemd"
        self.systemd.write_bytes(b"systemd executable")
        self.object = self.root / "sysroot/ostree/repo/objects/systemd.file"
        os.link(self.systemd, self.object)
        (self.root / "lib").symlink_to("usr/lib")
        (self.root / "ostree").symlink_to("sysroot/ostree")

    def test_removes_conflicting_ostree_hardlinks_and_preserves_live_paths(self):
        self.assertEqual(self.systemd.stat().st_ino, self.object.stat().st_ino)
        self.assertEqual(self.systemd.stat().st_nlink, 2)
        result = fixture.flatten_root(self.root)
        self.assertEqual(self.systemd.read_bytes(), b"systemd executable")
        self.assertEqual(self.systemd.stat().st_nlink, 1)
        self.assertFalse((self.root / "sysroot/ostree/repo").exists())
        self.assertTrue((self.root / "ostree").is_dir())
        self.assertEqual(fixture.resolve_image_path(self.root, Path("lib/systemd/systemd")),
                         Path("usr/lib/systemd/systemd"))
        self.assertEqual(result["removed_paths"], ["sysroot/ostree/repo"])

    def test_rejects_indirect_runtime_symlink_into_repository_before_deletion(self):
        (self.root / "usr/lib/needed-object").symlink_to("/ostree/repo/objects/systemd.file")
        with self.assertRaisesRegex(fixture.FixtureError, "runtime symlink depends"):
            fixture.flatten_root(self.root)
        self.assertTrue(self.object.is_file())
        self.assertEqual(self.systemd.stat().st_nlink, 2)

    def test_preserves_unrelated_bootc_link_and_scaffolding(self):
        (self.root / "usr/lib/bootc").mkdir()
        link = self.root / "usr/lib/bootc/storage"
        link.symlink_to("../../../../sysroot/ostree/bootc/storage")
        fixture.flatten_root(self.root)
        self.assertEqual(os.readlink(link), "../../../../sysroot/ostree/bootc/storage")
        self.assertTrue((self.root / "sysroot/ostree").is_dir())

    def test_rejects_unmaterialized_runtime_root(self):
        (self.root / "etc").rmdir()
        (self.root / "etc").symlink_to("sysroot/ostree/repo/objects")
        with self.assertRaisesRegex(fixture.FixtureError, "symlink"):
            fixture.flatten_root(self.root)
        self.assertTrue(self.object.is_file())

    def test_generic_export_checks_core_labels_and_optional_reporter_when_present(self):
        core = ["/usr/lib/systemd/systemd", "/usr/bin/bash", "/usr/lib/systemd/systemd-journald"]
        self.assertEqual(fixture.required_label_paths(self.root), core)
        reporter = self.root / "usr/libexec/pocketfed-liveboot-check"
        reporter.parent.mkdir()
        reporter.write_text("#!/bin/sh\n")
        self.assertEqual(fixture.required_label_paths(self.root), core + ["/usr/libexec/pocketfed-liveboot-check"])


if __name__ == "__main__":
    unittest.main()
