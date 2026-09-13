#!/usr/bin/env python3
"""Host-only checks for kernel provenance and mixed/incomplete build rejection."""

import argparse
import gzip
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location("build_kernel", Path(__file__).with_name("build-kernel.py"))
kernel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kernel)


class KernelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.build = self.base / "build"
        self.release = "7.1.2-test+"
        self.dtb = "qcom/sdm670-google-sargo.dtb"
        self.put(".config", "CONFIG_ARM64=y\nCONFIG_MODULES=y\n")
        self.put("System.map", "00000001 T example\n")
        self.put("modules.order", "drivers/example.o\n")
        self.put("include/generated/utsrelease.h", f'#define UTS_RELEASE "{self.release}"\n')
        self.put("include/config/kernel.release", self.release + "\n")
        image = bytearray(512)
        image[56:60] = b"ARM\x64"
        struct.pack_into("<Q", image, 16, len(image))
        banner = ("Linux version " + self.release + " (builder@host)\0").encode()
        image[128:128 + len(banner)] = banner
        self.put("arch/arm64/boot/Image.gz", gzip.compress(image, mtime=0))
        dtb = bytearray(40)
        struct.pack_into(">II", dtb, 0, 0xD00DFEED, len(dtb))
        self.put("arch/arm64/boot/dts/" + self.dtb, dtb)

    def put(self, name, value):
        path = self.build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)
        return path

    def installed(self):
        install = self.base / "install"
        root = install / "lib/modules" / self.release
        (root / "kernel/drivers").mkdir(parents=True)
        (root / "kernel/drivers/example.ko").write_bytes(b"a module")
        for name in ("modules.dep", "modules.dep.bin", "modules.alias", "modules.builtin", "modules.symbols"):
            (root / name).write_bytes(b"metadata\n")
        (root / "modules.dep").write_text("kernel/drivers/example.ko:\n")
        return install, root

    def test_accepts_coherent_image_dtb_config_and_release(self):
        paths = kernel.verify_kernel(self.build, self.dtb, self.release)
        self.assertEqual(paths["image"], self.build / "arch/arm64/boot/Image.gz")

    def test_rejects_kernel_release_mixed_with_other_outputs(self):
        self.put("include/generated/utsrelease.h", '#define UTS_RELEASE "wrong-release"\n')
        with self.assertRaisesRegex(kernel.BuildError, "UTS_RELEASE"):
            kernel.verify_kernel(self.build, self.dtb, self.release)
        self.put("include/generated/utsrelease.h", '#define UTS_RELEASE "7.1.2-other"\n')
        with self.assertRaisesRegex(kernel.BuildError, "release banner"):
            kernel.verify_kernel(self.build, self.dtb, "7.1.2-other")

    def test_rejects_truncated_dtb_and_non_arm64_image(self):
        path = self.build / "arch/arm64/boot/dts" / self.dtb
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(kernel.BuildError, "complete flattened"):
            kernel.verify_kernel(self.build, self.dtb, self.release)
        self.put("arch/arm64/boot/Image.gz", gzip.compress(b"other architecture"))
        with self.assertRaisesRegex(kernel.BuildError, "arm64 Image"):
            kernel.verify_kernel(self.build, self.dtb, self.release)

    def test_tracks_exact_built_modules_and_rejects_duplicates(self):
        path = self.put("drivers/example.ko", b"actual built module")
        self.assertEqual(kernel.built_module_inventory(self.build, self.build / "modules.order"),
                         {"drivers/example.ko": kernel.sha256(path)})
        self.put("modules.order", "drivers/example.o\ndrivers/example.o\n")
        with self.assertRaisesRegex(kernel.BuildError, "duplicate"):
            kernel.built_module_inventory(self.build, self.build / "modules.order")

    def test_rejects_dtb_traversal_and_symlink_parent(self):
        for name in ("/absolute", "../outside", "qcom/../outside", "qcom//file", "./file", "qcom\\file"):
            with self.subTest(name=name), self.assertRaises(kernel.BuildError):
                kernel.relative(name)
        (self.build / "arch/arm64/boot/dts/alias").symlink_to(self.base)
        with self.assertRaisesRegex(kernel.BuildError, "symlink"):
            kernel.safe_child(self.build, "arch/arm64/boot/dts/alias/file")

    def test_complete_modules_match_build_order_and_vermagic(self):
        install, root = self.installed()
        (root / "build").symlink_to("/some/source/tree")
        commands = mock.Mock()
        commands.run.return_value = self.release + " SMP preempt mod_unload aarch64"
        files = kernel.verify_modules(install, self.release, self.build / "modules.order", commands, "modinfo")
        self.assertFalse((root / "build").is_symlink())
        self.assertIn(f"lib/modules/{self.release}/modules.dep.bin", files)
        self.assertEqual(len(files), 6)

    def test_missing_extra_and_duplicate_installed_modules_fail(self):
        install, root = self.installed()
        module = root / "kernel/drivers/example.ko"
        module.unlink()
        with self.assertRaisesRegex(kernel.BuildError, "modules.order"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", mock.Mock(), "modinfo")
        module.write_bytes(b"module")
        extra = root / "kernel/drivers/example.ko.zst"
        extra.write_bytes(b"duplicate")
        with self.assertRaisesRegex(kernel.BuildError, "modules.order"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", mock.Mock(), "modinfo")

    def test_bad_module_vermagic_and_missing_metadata_fail(self):
        install, root = self.installed()
        commands = mock.Mock()
        commands.run.return_value = "7.1.2-some-other-build SMP"
        with self.assertRaisesRegex(kernel.BuildError, "vermagic"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", commands, "modinfo")
        (root / "modules.dep.bin").unlink()
        with self.assertRaisesRegex(kernel.BuildError, "depmod metadata"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", commands, "modinfo")

    def test_incomplete_or_dangling_dependencies_fail(self):
        install, root = self.installed()
        (root / "modules.dep").write_text("")
        with self.assertRaisesRegex(kernel.BuildError, "every installed module"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", mock.Mock(), "modinfo")
        (root / "modules.dep").write_text("kernel/drivers/example.ko: kernel/missing.ko\n")
        with self.assertRaisesRegex(kernel.BuildError, "missing, empty"):
            kernel.verify_modules(install, self.release, self.build / "modules.order", mock.Mock(), "modinfo")

    def test_blocks_install_redirection_and_inherited_make_overrides(self):
        for value in ("INSTALL_MOD_PATH=/", "O=/other", "M=drivers/foo", "CONFIG_MODULE_SIG_FORCE=n", "CC"):
            with self.subTest(value=value), self.assertRaises(kernel.BuildError):
                kernel.make_variables([value])
        with mock.patch.dict(os.environ, {"MAKEFLAGS": "-e", "INSTALL_MOD_PATH": "/", "KBUILD_EXTMOD": "/tmp/m", "CC": "old-tool"}):
            env = kernel.build_environment()
            for key in ("MAKEFLAGS", "INSTALL_MOD_PATH", "KBUILD_EXTMOD", "CC"):
                self.assertNotIn(key, env)
            self.assertEqual(env["KCONFIG_NOSILENTUPDATE"], "1")
        self.assertEqual(kernel.make_variables(["CC=ccache clang", "LOCALVERSION=-camera"]),
                         {"CC": "ccache clang", "LOCALVERSION": "-camera"})

    def test_existing_candidate_is_not_overwritten(self):
        source = self.base / "source"
        source.mkdir()
        (source / "Makefile").write_text("# source\n")
        output = self.base / "candidate"
        output.mkdir()
        marker = output / "valuable"
        marker.write_bytes(b"keep me")
        args = argparse.Namespace(kernel_tree=source, build_dir=self.build, output=output,
                                  dtb=self.dtb, make_var=[], llvm=None)
        with self.assertRaisesRegex(kernel.BuildError, "already exists"):
            kernel.produce(args)
        self.assertEqual(marker.read_bytes(), b"keep me")

    def test_does_not_reassociate_existing_build_with_different_source(self):
        source = self.base / "source"
        source.mkdir()
        (source / "Makefile").write_text("# source\n")
        (self.build / "source").symlink_to(self.base / "other-source")
        output = self.base / "candidate"
        args = argparse.Namespace(kernel_tree=source, build_dir=self.build, output=output,
                                  dtb=self.dtb, make_var=[], llvm=None, no_build=False)
        with self.assertRaisesRegex(kernel.BuildError, "another kernel tree"):
            kernel.produce(args)
        self.assertFalse(output.exists())

    def test_records_staged_and_unstaged_source_plus_untracked_hashes(self):
        source = self.base / "source"
        source.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(source), *args], check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git("init", "-q")
        (source / "driver.c").write_text("original\n")
        git("add", "driver.c")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        (source / "driver.c").write_text("staged\n")
        git("add", "driver.c")
        (source / "driver.c").write_text("final content\n")
        (source / "new.c").write_text("new source\n")
        state, patch = kernel.source_state(source, ())
        self.assertTrue(state["dirty"])
        self.assertIn(b"-original", patch)
        self.assertIn(b"+final content", patch)
        self.assertEqual(state["untracked"]["new.c"]["sha256"], kernel.sha256(source / "new.c"))
        self.assertEqual(len(state["commit"]), 40)


if __name__ == "__main__":
    unittest.main()
