#!/usr/bin/env python3
"""Regression checks for false release passes; fixtures never open cameras."""
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


observe = runpy.run_path(str(Path(__file__).with_name("power-state.py")))["observe"]


class ReleaseEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sys, self.proc = self.root / "sys", self.root / "proc"
        self.proc.mkdir()
        self.uid = patch("os.geteuid", return_value=0)
        self.uid.start()
        self.addCleanup(self.uid.stop)
        self.put(self.proc / "sys/kernel/random/boot_id", "fixture-boot")
        self.isp = self.sys / "devices/isp"
        self.put(self.isp / "media9/dev", "240:9")
        for index, name in enumerate(("imx363", "imx355", "lc898219xi", "msm_vfe0_video0")):
            node = self.sys / f"class/video4linux/v4l-subdev{index + 20}"
            self.put(node / "name", name)
            # Reuse /dev/null's identity for a safe real stat() holder fixture.
            self.put(node / "dev", "1:3" if name == "imx363" else f"81:{index}")
            if name.startswith("msm_"):
                (node / "device").symlink_to(self.isp, target_is_directory=True)
            else:
                power = self.sys / f"bus/i2c/devices/3-00{index:02}"
                self.put(power / "name", name)
                self.put(power / "power/runtime_status", "suspended")

    @staticmethod
    def put(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def report(self):
        return observe(self.sys, self.proc)

    def test_complete_released_and_renumbered_media(self):
        report = self.report()
        self.assertEqual(report["release_status"], "released")
        self.assertEqual(report["media_nodes"], ["/dev/media9"])

    def test_empty_discovery_cannot_pass(self):
        self.assertEqual(observe(self.root / "absent", self.proc)["release_status"], "unknown")

    def test_missing_lens_power_cannot_pass(self):
        (self.sys / "bus/i2c/devices/3-0002/name").unlink()
        self.assertEqual(self.report()["release_status"], "unknown")

    def test_missing_lens_node_cannot_pass(self):
        (self.sys / "class/video4linux/v4l-subdev22/name").unlink()
        self.assertEqual(self.report()["release_status"], "unknown")

    def test_active_sensor_is_busy(self):
        self.put(self.sys / "bus/i2c/devices/3-0000/power/runtime_status", "active")
        self.assertEqual(self.report()["release_status"], "busy")

    def test_unreadable_runtime_state_cannot_pass(self):
        (self.sys / "bus/i2c/devices/3-0000/power/runtime_status").unlink()
        self.assertEqual(self.report()["release_status"], "unknown")

    def test_alias_holder_detected_by_device_identity(self):
        descriptor = self.proc / "456/fd/3"
        descriptor.parent.mkdir(parents=True)
        descriptor.symlink_to("/dev/null")
        self.put(self.proc / "456/comm", "holder-fixture")
        report = self.report()
        self.assertEqual(report["release_status"], "busy")
        self.assertEqual(report["holders"][0]["descriptors"][0]["device"], "/dev/null")

    def test_non_root_cannot_pass(self):
        with patch("os.geteuid", return_value=1000):
            self.assertEqual(self.report()["release_status"], "unknown")

    def test_uninspectable_process_cannot_pass(self):
        target = self.proc / "456/fd"
        target.parent.mkdir()
        original = Path.iterdir

        def inspect(path):
            if path == target:
                raise PermissionError("fixture denied")
            return original(path)

        with patch.object(Path, "iterdir", inspect):
            self.assertEqual(self.report()["release_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
