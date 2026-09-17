#!/usr/bin/env python3
"""Host-only checks for adding external kmods to a candidate bundle; no RPMs."""

import importlib.util
import json
import lzma
from pathlib import Path
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "bundle_add_kmods", Path(__file__).with_name("bundle-add-kmods.py"))
bundle_add = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle_add)


def make_bundle(base, release="6.1.0-test.aarch64"):
    bundle = base / "bundle"
    release_root = bundle / "modules" / "lib" / "modules" / release
    (release_root / "kernel").mkdir(parents=True)
    (release_root / "kernel/regular.ko.xz").write_bytes(b"regular module")
    (release_root / "modules.dep").write_text("kernel/regular.ko.xz:\n")
    (release_root / "modules.builtin").write_text("")
    (release_root / "modules.alias").write_bytes(b"")
    (bundle / "dtb/qcom").mkdir(parents=True)
    (bundle / "Image.gz").write_bytes(b"image")
    (bundle / "dtb/qcom/x.dtb").write_bytes(b"dtb")
    (bundle / "kernel.config").write_bytes(b"CONFIG_ARM64=y\n")
    (bundle / "System.map").write_bytes(b"map")
    module_files = {
        f"lib/modules/{release}/kernel/regular.ko.xz": bundle_add.build_kernel.sha256(
            release_root / "kernel/regular.ko.xz"),
        f"lib/modules/{release}/modules.dep": bundle_add.build_kernel.sha256(release_root / "modules.dep"),
        f"lib/modules/{release}/modules.builtin": bundle_add.build_kernel.sha256(release_root / "modules.builtin"),
        f"lib/modules/{release}/modules.alias": bundle_add.build_kernel.sha256(release_root / "modules.alias"),
    }
    manifest = {"schema_version": 1, "release": release,
                "image": {"path": "Image.gz", "sha256": bundle_add.build_kernel.sha256(bundle / "Image.gz")},
                "dtb": {"path": "dtb/qcom/x.dtb", "sha256": bundle_add.build_kernel.sha256(bundle / "dtb/qcom/x.dtb")},
                "modules_install": "modules", "module_files": module_files}
    (bundle / "bundle.json").write_text(json.dumps(manifest))
    (bundle / "provenance.json").write_text(json.dumps({"schema_version": 1, "artifacts": {}}))
    (bundle / "early-modules.txt").write_text("")
    return bundle, release


def make_ko(base, name="x.ko"):
    path = base / name
    path.write_bytes(b"external module body")
    return path


def fake_depmod(output, release, depmod="depmod"):
    root = output / "modules" / "lib" / "modules" / release
    with (root / "modules.dep").open("a") as stream:
        stream.write("updates/test/x.ko.xz:\n")


class AddKmodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def run_add(self, sources=None):
        bundle, release = make_bundle(self.base)
        ko = make_ko(self.base)
        sources = sources if sources is not None else {"files": {}, "modules": {}}
        with mock.patch.object(bundle_add, "module_vermagic",
                               return_value=release + " SMP preempt mod_unload aarch64"), \
                mock.patch.object(bundle_add, "run_depmod", side_effect=fake_depmod):
            result = bundle_add.add_kmods(bundle, self.base / "out", [ko], "test", sources)
        return bundle, release, ko, result

    def test_compresses_places_and_updates_manifest_and_provenance(self):
        sources = {"files": {"drivers/foo/x.c": "a" * 40},
                   "modules": {"x": ["drivers/foo/x.c"]}}
        bundle, release, ko, result = self.run_add(sources)
        output = self.base / "out"
        installed = output / "modules/lib/modules" / release / "updates/test/x.ko.xz"
        self.assertTrue(installed.is_file())
        self.assertEqual(lzma.decompress(installed.read_bytes()), ko.read_bytes())
        manifest = json.loads((output / "bundle.json").read_text())
        key = f"lib/modules/{release}/updates/test/x.ko.xz"
        self.assertIn(key, manifest["module_files"])
        self.assertEqual(manifest["release"], release)
        self.assertEqual(manifest["image"], json.loads((bundle / "bundle.json").read_text())["image"])
        self.assertEqual(result, output / "bundle.json")
        self.assertFalse((bundle / "modules/lib/modules" / release / "updates").exists())
        provenance = json.loads((output / "provenance.json").read_text())
        self.assertEqual(len(provenance["kmods"]), 1)
        entry = provenance["kmods"][0]
        self.assertEqual(entry["module"], "x")
        self.assertEqual(entry["sha256"], bundle_add.build_kernel.sha256(ko))
        self.assertEqual(entry["sources"], [{"path": "drivers/foo/x.c", "blob": "a" * 40}])
        self.assertEqual(entry["installed"], f"lib/modules/{release}/updates/test/x.ko.xz")
        self.assertTrue((output / "early-modules.txt").read_text().strip())

    def test_refuses_release_mismatch_before_writing_output(self):
        bundle, release = make_bundle(self.base)
        ko = make_ko(self.base)
        with mock.patch.object(bundle_add, "module_vermagic",
                               return_value="9.9.9-other SMP preempt mod_unload aarch64"):
            with self.assertRaisesRegex(bundle_add.BundleError, "does not match bundle release"):
                bundle_add.add_kmods(bundle, self.base / "out", [ko], "test", {"files": {}, "modules": {}})
        self.assertFalse((self.base / "out").exists())

    def test_refuses_existing_output_and_missing_sources(self):
        bundle, release = make_bundle(self.base)
        ko = make_ko(self.base)
        (self.base / "out").mkdir()
        with mock.patch.object(bundle_add, "module_vermagic",
                               return_value=release + " SMP preempt mod_unload aarch64"):
            with self.assertRaisesRegex(bundle_add.BundleError, "already exists"):
                bundle_add.add_kmods(bundle, self.base / "out", [ko], "test", {"files": {}, "modules": {}})
            (self.base / "out").rmdir()
            sources = {"files": {}, "modules": {"x": ["drivers/foo/x.c"]}}
            with self.assertRaisesRegex(bundle_add.BundleError, "lacks a blob"):
                bundle_add.add_kmods(bundle, self.base / "out", [ko], "test", sources)
        self.assertFalse((self.base / "out").exists())

    def test_collect_kmods_rejects_missing_or_wrong_files(self):
        with self.assertRaisesRegex(bundle_add.BundleError, "no .ko modules"):
            bundle_add.collect_kmods(None, [])
        wrong = self.base / "x.txt"
        wrong.write_text("not a module")
        with self.assertRaisesRegex(bundle_add.BundleError, "regular .ko"):
            bundle_add.collect_kmods(None, [wrong])


if __name__ == "__main__":
    unittest.main()
