#!/usr/bin/env python3
"""Exercise label acceptance against real, tiny EROFS images; no device use."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("verify_root_labels", HERE / "verify-root-labels.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


@unittest.skipUnless(all(shutil.which(tool) for tool in ["mkfs.erofs", "fsck.erofs", "matchpathcon"]),
                     "EROFS and libselinux host tools required")
class RootLabelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pocketfed-label-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "root"
        self.contexts = self.base / "file_contexts"
        labels = ["init_exec_t", "shell_exec_t", "syslogd_exec_t", "bin_t"]
        lines = ["/.* system_u:object_r:default_t:s0"]
        for path, label in zip(VERIFY.BOOT_PATHS, labels):
            file = self.root / path.lstrip("/")
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"fixture payload\n")
            file.chmod(0o755)
            lines.append(f"{re.escape(path)} -- system_u:object_r:{label}:s0")
        self.contexts.write_text("\n".join(lines) + "\n")

    def build(self, name):
        image = self.base / (name + ".erofs")
        subprocess.run(["mkfs.erofs", "--file-contexts=" + str(self.contexts),
                        str(image), str(self.root)], check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        return image

    def test_rejects_ostree_hardlink_labels_and_accepts_flattened_image(self):
        objects = self.root / "sysroot/ostree/repo/objects/ab"
        objects.mkdir(parents=True)
        for index, path in enumerate(VERIFY.BOOT_PATHS[:3]):
            os.link(self.root / path.lstrip("/"), objects / f"{index}.file")
        bad = VERIFY.verify_root_labels(self.build("hardlinked"), self.contexts)
        self.assertEqual(bad["result"], "fail")
        self.assertEqual([check["actual"] for check in bad["checks"][:3]],
                         ["system_u:object_r:default_t:s0"] * 3)
        shutil.rmtree(self.root / "sysroot")
        good = VERIFY.verify_root_labels(self.build("flattened"), self.contexts)
        self.assertEqual(good["result"], "pass", good)

    def test_expectations_come_from_supplied_contexts(self):
        image = self.build("original-contexts")
        self.contexts.write_text(self.contexts.read_text().replace("shell_exec_t", "bin_t"))
        report = VERIFY.verify_root_labels(image, self.contexts)
        bash = next(check for check in report["checks"] if check["path"] == "/usr/bin/bash")
        self.assertEqual(bash["expected"], "system_u:object_r:bin_t:s0")
        self.assertEqual(bash["actual"], "system_u:object_r:shell_exec_t:s0")
        self.assertFalse(bash["matches"])
        self.assertEqual(report["result"], "fail")

    def test_missing_health_reporter_rejects_image(self):
        (self.root / "usr/libexec/pocketfed-liveboot-check").unlink()
        image = self.build("missing-reporter")
        report = VERIFY.verify_root_labels(image, self.contexts)
        self.assertEqual(report["result"], "fail")
        self.assertIn("error", report["checks"][-1])
        generic = VERIFY.verify_root_labels(image, self.contexts, VERIFY.BOOT_PATHS[:3])
        self.assertEqual(generic["result"], "pass")
        self.assertEqual(len(generic["checks"]), 3)


if __name__ == "__main__":
    unittest.main()
