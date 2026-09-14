#!/usr/bin/env python3
"""Overlay provenance inventories must agree with actual overlay contents."""
import json
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class OverlayInventoryTests(unittest.TestCase):
    def test_masked_units_inventory_matches_dev_null_links(self):
        """Every /dev/null mask under etc/systemd/system is listed exactly once
        in the overlay's policy.json masked_units, and nothing else is. The
        inventory is order-insensitive; only membership and duplicates matter."""
        overlays = [ROOT / "overlay"] + sorted((ROOT / "overlays").iterdir())
        overlays = [path for path in overlays if path.is_dir()]
        self.assertTrue(overlays, "no overlay directories found")
        for overlay in overlays:
            with self.subTest(overlay=overlay.relative_to(ROOT)):
                system = overlay / "etc" / "systemd" / "system"
                masked = sorted(
                    path.name for path in system.glob("*")
                    if path.is_symlink() and os.readlink(path) == "/dev/null")
                policy = json.loads(
                    (overlay / "usr/lib/pocketfed-liveboot/policy.json").read_text())
                inventory = policy["masked_units"]
                self.assertEqual(len(inventory), len(set(inventory)),
                                 "masked_units contains duplicate entries")
                self.assertEqual(sorted(inventory), masked)


if __name__ == "__main__":
    unittest.main()
