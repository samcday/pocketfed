import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from qcom_baseband_profile_manager.config import Config
from qcom_baseband_profile_manager.data import ConfigId, PLMN
from qcom_baseband_profile_manager import main


class ConfigTests(unittest.TestCase):
    def test_multiple_carriers_in_same_country(self):
        config = Config()
        config.parse_profiles({
            "telstra": {"mcc": "505", "mnc": "01", "mnc_len": 2,
                        "profiles": ["01:02"]},
            "optus": {"mcc": "505", "mnc": "02", "mnc_len": 2,
                      "profiles": ["03:04"]},
        })
        self.assertEqual(config.resolve_provider_profile(PLMN("505", "01")),
                         [ConfigId("01:02")])
        self.assertEqual(config.resolve_provider_profile(PLMN("505", "02")),
                         [ConfigId("03:04")])
        self.assertEqual(config.resolve_provider_profile(PLMN("505", "99")), [])


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        # These tests exercise asyncio scheduling, not GLib IO. A standalone
        # selector loop avoids taking ownership of the module's GLib context.
        self.loop = asyncio.SelectorEventLoop()
        self.errors = []
        self.loop.set_exception_handler(lambda loop, context: self.errors.append(context))
        self.loop_patch = patch.object(main, "LOOP", self.loop)
        self.loop_patch.start()

    def tearDown(self):
        for task in asyncio.all_tasks(self.loop):
            task.cancel()
        self.loop.run_until_complete(asyncio.sleep(0))
        self.loop_patch.stop()
        self.loop.close()

    def drain(self):
        self.loop.run_until_complete(asyncio.sleep(0.01))
        self.assertEqual(self.errors, [])

    def test_card_callback_runs_once(self):
        uim = main.UIM(None)
        uim.cb_card_status = AsyncMock()
        new = (0, 65535, {})
        uim.parse_uim_card_status = Mock(return_value=new)
        uim._on_uim_card_status(None, Mock())
        self.drain()
        uim.cb_card_status.assert_awaited_once_with({}, new)
        self.assertFalse(uim._callbacks)

    def test_slot_callback_is_a_task_not_a_callback(self):
        uim = main.UIM(None)
        uim.cb_slot_status = AsyncMock()
        uim.parse_slot_status = Mock(return_value={1: "present"})
        uim._on_uim_slot_status(None, Mock())
        self.drain()
        uim.cb_slot_status.assert_awaited_once_with({}, {1: "present"})

    def test_wait_for_sim_schedules_polling_once(self):
        manager = main.ProfileManager("qrtr://0")
        manager.wait_for_usim_periodic = AsyncMock()
        self.loop.run_until_complete(manager.on_enter_wait_for_usim())
        self.drain()
        manager.wait_for_usim_periodic.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
