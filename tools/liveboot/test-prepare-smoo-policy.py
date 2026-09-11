#!/usr/bin/python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("policy_helper", Path(__file__).with_name("prepare-smoo-policy.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class PolicyDeltaTests(unittest.TestCase):
    def test_accepts_only_exact_allow_and_top_level_reordering(self):
        before = '(type kernel_t)\n(type device_t)\n'
        after = '(type device_t)\n' + helper.ALLOW + '\n(type kernel_t)\n'
        self.assertEqual(helper.verify_delta(before, after)["added_forms"], [helper.ALLOW])

    def test_rejects_removals_extra_rules_and_permissive_types(self):
        before = '(type kernel_t)\n(type device_t)\n'
        for after in [helper.ALLOW, before + helper.ALLOW + '\n(typepermissive kernel_t)',
                      before + helper.ALLOW + '\n(allow kernel_t device_t (chr_file (write)))']:
            with self.assertRaises(helper.PolicyError):
                helper.verify_delta(before, after)

    def test_preserves_nested_condition_semantics(self):
        before = '(booleanif flag\n  (true (allow a b (file (read))))\n  (false (allow c d (file (write)))))'
        after = '(booleanif flag\n  (false (allow a b (file (read))))\n  (true (allow c d (file (write)))))'
        with self.assertRaises(helper.PolicyError):
            helper.verify_delta(before, after + helper.ALLOW)

    def test_handles_quoted_parentheses_and_rejects_partial_forms(self):
        self.assertEqual(sum(helper.cil_forms('(filecon "/path/(x)" file context)').values()), 1)
        for broken in ['(type a', ')', 'outside']:
            with self.assertRaises(helper.PolicyError):
                helper.cil_forms(broken)


if __name__ == '__main__':
    unittest.main()
