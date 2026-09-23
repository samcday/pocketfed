#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline tests for relay.py; no relay module, board or root needed."""

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "relay", Path(__file__).resolve().with_name("relay.py"))
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

# Cold boot of the DB410c as captured on its console, cut after the countdown.
BOOT = (b"B -    241987 - SBL1, Start\r\n"
        b"S - DDR Frequency, 400 MHz\r\n\r\n\r\n"
        b"U-Boot 2026.07-rc4-00430-gb89b7bb08426-dirty (Jun 12 2026 - 23:01:13 +1000)\r\n"
        b"Qualcomm-DragonBoard 410C\r\n"
        b"\x1b[2KHit any key to stop autoboot:  2")


class ProtocolTests(unittest.TestCase):
    def test_dcttech_reports(self):
        self.assertEqual(bytes(relay.dcttech_report(2, True)).hex(), "00ff02000000000000")
        self.assertEqual(bytes(relay.dcttech_report(1, False)).hex(), "00fd01000000000000")
        states = relay.dcttech_states(b"\x00ABCDE\x00\x00\x05")
        self.assertEqual([states[n] for n in range(1, 5)], [True, False, True, False])

    def test_hidraw_ioctl_numbers(self):
        self.assertEqual(relay.hidioc(0x06, 9), 0xC0094806)  # HIDIOCSFEATURE(9)
        self.assertEqual(relay.hidioc(0x07, 9), 0xC0094807)  # HIDIOCGFEATURE(9)

    def test_console_markers(self):
        events = {}
        # A banner split across reads is recorded once its line is complete.
        self.assertIsNone(relay.scan_markers(BOOT[:80], events, 0.5))
        self.assertEqual(events, {"sbl1": 0.5})
        self.assertEqual(relay.scan_markers(BOOT, events, 1.0), "U-Boot 2026.07-rc4-00430-"
                         "gb89b7bb08426-dirty (Jun 12 2026 - 23:01:13 +1000)")
        self.assertEqual(events, {"sbl1": 0.5, "u-boot": 1.0, "autoboot": 1.0})


class ConfigTests(unittest.TestCase):
    def test_shipped_channel_map(self):
        config = relay.load_config(relay.CONFIG)
        channel = config.channel("db410c-power")
        self.assertIs(config.channel("1"), channel)
        self.assertEqual((channel.wiring, channel.target), ("NC", "db410c"))
        self.assertEqual([c.name for c in config.channels.values()], ["db410c-power", "", "", ""])
        # Through NC the board is powered while the coil is off.
        self.assertEqual((channel.coil_for(True), channel.coil_for(False)), (False, True))
        self.assertEqual(config.targets["db410c"].smoo_usb, ("dead", "bee1"))

    def test_smoo_product(self):
        self.assertEqual(relay.smoo_product(["smoo-host", "--product-id", "0xBEE1"]), 0xBEE1)
        self.assertEqual(relay.smoo_product(["smoo-host", "--product-id=48865"]), 0xBEE1)
        self.assertIsNone(relay.smoo_product(["smoo-host", "--file", "root.img"]))


class FakeRelay:
    def __init__(self):
        self.coils, self.calls = {n: False for n in range(1, 5)}, []

    def set(self, channel, on):
        self.calls.append((channel, on))
        self.coils[channel] = on

    def read(self):
        return dict(self.coils)


class PowerCycleTests(unittest.TestCase):
    def setUp(self):
        self.target = relay.load_config(relay.CONFIG).targets["db410c"]
        self.relay = FakeRelay()
        quiet = mock.patch.object(relay, "progress")
        quiet.start()
        self.addCleanup(quiet.stop)

    def cycle(self, board_on_usb):
        with mock.patch.object(relay, "board_on_usb", board_on_usb):
            return relay.power_cycle(self.relay, self.target, 0.3, 1, None, None)

    def test_returns_to_fastboot(self):
        result = self.cycle(lambda target: None if self.relay.coils[1] else "fastboot")
        self.assertEqual(result["exit"], relay.EXIT_OK)
        self.assertEqual(self.relay.calls, [(1, True), (1, False)])
        self.assertIsNotNone(result["left_usb_after"])

    def test_power_that_never_went_away(self):
        result = self.cycle(lambda target: "fastboot")
        self.assertEqual(result["exit"], relay.EXIT_NOT_CUT)
        self.assertEqual(self.relay.calls[-1], (1, False))

    def test_silent_board(self):
        self.assertEqual(self.cycle(lambda target: None)["exit"], relay.EXIT_NO_SIGN)

    def test_interrupt_restores_power(self):
        def board_on_usb(target):
            if self.relay.coils[1]:
                raise KeyboardInterrupt  # e.g. SIGTERM while the power is off
            return None

        with self.assertRaises(KeyboardInterrupt):
            self.cycle(board_on_usb)
        self.assertEqual(self.relay.calls, [(1, True), (1, False)])

    def test_busy_evidence(self):
        uart = self.target.uart
        processes = [
            (10, ["/src/smoo-liveboot/smoo-host", "--product-id", "0xBEE1", "--file", "r.img"]),
            (11, ["smoo-host", "--file", "other-board.img"]),
            (12, ["fastboot", "-s", "bc72e60", "boot", "liveboot.img"]),
            (13, ["fastboot", "-s", "0123456789", "getvar", "all"]),
            (14, ["codex", "exec", "power-cycle bc72e60 when done"]),
            (15, ["tio", uart]),
        ]
        with mock.patch.object(relay, "processes", lambda: iter(processes)), \
                mock.patch.object(relay, "holds", lambda pid, dev: pid == 15), \
                mock.patch.object(relay, "board_on_usb", lambda target: "smoo"):
            reasons = relay.board_users(self.target)
        self.assertEqual([reason.split()[1] for reason in reasons[:3]], ["10", "12", "15"])
        self.assertIn("smoo gadget", reasons[3])
        self.assertEqual(len(reasons), 4)


if __name__ == "__main__":
    unittest.main()
