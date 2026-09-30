#!/usr/bin/python3
"""Host checks of bounded ordering; no firmware or device is accessed."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('trial', Path(__file__).with_name('trial-05.py'))
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class Lifetimes(unittest.TestCase):
    def exercise(self, fail_cycle=None, fail_stop=False):
        calls = []
        report = {'cycles_completed': 0, 'lifetimes_completed': 0,
                  'started_units': [], 'stopped_units': []}
        states = {unit: 'inactive' for unit in trial.LOADERS}

        def service(argv, **kwargs):
            action, unit = argv[1:]
            calls.append((action, unit))
            if action == 'stop' and fail_stop:
                return types.SimpleNamespace(returncode=1)
            states[unit] = 'active' if action == 'start' else 'inactive'
            return types.SimpleNamespace(returncode=0)

        def native(argv, root, evidence):
            cycle = int(argv[-1].split('=')[1])
            self.assertTrue(all(state == 'active' for state in states.values()))
            self.assertTrue(root.is_dir())
            calls.append(('native', cycle))
            return {'returncode': 0, 'verified': cycle != fail_cycle}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(trial, 'ROOT', Path(directory)), \
             patch.object(trial, 'unit_state', side_effect=lambda unit: {'ActiveState': states[unit]}), \
             patch.object(trial.subprocess, 'run', side_effect=service), \
             patch.object(trial, 'run_native', side_effect=native), \
             patch.object(trial, 'completed_sequence', side_effect=lambda result: result['verified']):
            evidence = types.SimpleNamespace(emit=lambda *args: None)
            error = None
            try:
                trial.exercise_lifetimes(report, evidence)
            except AssertionError as caught:
                error = caught
        return calls, report, error

    def test_fifty_cycles_and_ten_ordered_shutdowns(self):
        calls, report, error = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(report['cycles_completed'], 50)
        self.assertEqual(report['lifetimes_completed'], 10)
        expected = []
        for lifetime in range(10):
            expected += [('start', unit) for unit in trial.LOADERS]
            expected += [('native', cycle) for cycle in range(lifetime * 5 + 1, lifetime * 5 + 6)]
            expected += [('stop', unit) for unit in reversed(trial.LOADERS)]
        self.assertEqual(calls, expected)

    def test_unverified_native_stops_run_without_cleanup_or_retry(self):
        calls, report, error = self.exercise(fail_cycle=2)
        self.assertIsNotNone(error)
        self.assertEqual(report['cycles_completed'], 1)
        self.assertEqual(report['lifetimes_completed'], 0)
        self.assertEqual(calls[-1], ('native', 2))
        self.assertFalse(any(action == 'stop' for action, _ in calls))

    def test_failed_loader_stop_prevents_next_lifetime(self):
        calls, report, error = self.exercise(fail_stop=True)
        self.assertIsNotNone(error)
        self.assertEqual(report['cycles_completed'], 5)
        self.assertEqual(report['lifetimes_completed'], 0)
        self.assertEqual(calls[-1], ('stop', trial.LOADERS[-1]))
        self.assertEqual(sum(action == 'start' for action, _ in calls), 3)


if __name__ == '__main__':
    unittest.main()
