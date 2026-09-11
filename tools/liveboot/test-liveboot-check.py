#!/usr/bin/env python3
"""Check handoff reporting without running guest commands or accessing devices."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest import mock


REPORTER = Path(__file__).resolve().parent / "overlay/usr/libexec/pocketfed-liveboot-check"


class HandoffReportTests(unittest.TestCase):
    def report(self, labels_state, root_mode="usb", resident=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "cmdline").write_text(f"pocketfed.liveboot=test-run pocketfed.root_mode={root_mode}\n")
            (root / "root-mode.json").write_text(json.dumps(resident or {}))
            (root / "modules.dep").write_text("")

            def path(name):
                return {
                    "/proc/cmdline": root / "cmdline",
                    "/run/kboop/root-mode.json": root / "root-mode.json",
                    "/run/pocketfed-liveboot": root / "result",
                    "/usr/lib/modules/test/modules.dep": root / "modules.dep",
                }[name]

            def command(argv, **kwargs):
                answers = {
                    ("uname", "-r"): "test",
                    ("findmnt", "-n", "-o", "FSTYPE", "/"): "overlay",
                    ("findmnt", "-n", "-o", "SOURCE,FSTYPE", "-T", "/usr/lib/modules/test"):
                        "/dev/loop1 erofs" if root_mode == "ram" else "/dev/ublkb0 erofs",
                    ("systemctl", "is-enabled", "qbootctl.service"): "masked",
                    ("systemctl", "is-enabled", "usb-signaller.service"): "masked",
                    ("systemctl", "is-active", "pocketfed-liveboot-labels.service"): labels_state,
                    ("systemctl", "--failed", "--no-legend", "--plain", "--no-pager"):
                        "unrelated.service loaded failed failed Diagnostic only",
                    ("getenforce",): "Enforcing",
                }
                return subprocess.CompletedProcess(argv, 0, answers[tuple(argv)])

            output = io.StringIO()
            with mock.patch("pathlib.Path", side_effect=path), \
                    mock.patch("subprocess.run", side_effect=command), \
                    contextlib.redirect_stdout(output), \
                    self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(REPORTER), run_name="__main__")
            result = json.loads((root / "result/result.json").read_text())
            self.assertIn("POCKETFED_LIVEBOOT_RESULT=", output.getvalue())
            return stopped.exception.code, result

    def test_unrelated_failed_units_remain_diagnostics(self):
        status, result = self.report("active")
        self.assertEqual(status, False)
        self.assertEqual(result["result"], "pass")
        self.assertIn("unrelated.service", result["failed_units"][0])
        self.assertEqual(result["scope"], "systemd handoff; hardware subsystems not yet accepted")

    def test_ram_requires_verified_detached_storage(self):
        resident = {"mode": "ram", "smoo_detached": True, "hashes_verified": True,
                    "rootfs": {"device": "/dev/loop0"}, "modules": {"device": "/dev/loop1"}}
        status, result = self.report("active", "ram", resident)
        self.assertEqual(status, 0)
        self.assertTrue(result["checks"]["root_transport_ready"])
        for changed in ({"smoo_detached": False}, {"hashes_verified": False},
                        {"modules": {"device": "/dev/loop2"}}):
            status, result = self.report("active", "ram", resident | changed)
            self.assertEqual(status, 1)
            self.assertFalse(result["checks"]["root_transport_ready"])

    def test_failed_label_repair_emits_handoff_failure(self):
        status, result = self.report("failed")
        self.assertEqual(status, True)
        self.assertEqual(result["result"], "fail")
        self.assertFalse(result["checks"]["writable_root_labels_restored"])


if __name__ == "__main__":
    unittest.main()
