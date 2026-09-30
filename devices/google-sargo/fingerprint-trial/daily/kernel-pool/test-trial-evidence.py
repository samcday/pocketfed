#!/usr/bin/python3
"""Host regressions for lost output and status when post-probe cleanup fails."""
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest

from trial_evidence import Evidence, completed_sequence, run_native


class EvidenceTests(unittest.TestCase):
    def test_both_streams_survive_console_failure_and_cleanup_never_reached(self):
        records = []

        def broken_console(data):
            records.append(data)
            if len(records) > 2:
                raise OSError(errno.EIO, 'simulated terminal hangup')
            return len(data)

        child = ('import os,sys; '
                 'os.write(1,b"FPC_CPU_READY cpu=7 pid=1 disposable=true\\npartial"); '
                 'os.write(2,b"E"*70000+b"\\nlast stderr"); '
                 'os.write(1,b" line without newline"); sys.exit(7)')
        with tempfile.TemporaryDirectory() as directory:
            evidence = Evidence(directory, broken_console)
            result = run_native([sys.executable, '-c', child], directory, evidence)
            evidence.close()
            # A subsequent blocked/failed cleanup cannot prevent this evidence existing.
            saved = json.loads((Path(directory) / 'native-result.json').read_text())
            self.assertEqual(saved['returncode'], 7)
            self.assertEqual(result['returncode'], 7)
            self.assertTrue(saved['evidence_errors'])
            self.assertEqual((Path(directory) / 'native-stderr.log').read_bytes(),
                             b'E' * 70000 + b'\nlast stderr')
            self.assertTrue((Path(directory) / 'native-stdout.log').read_bytes().endswith(
                b'partial line without newline'))
            events = (Path(directory) / 'events.jsonl').read_text()
            self.assertIn('FPC_POOL_NATIVE_RESULT', events)
            self.assertTrue(all(len(record) <= 900 for record in records))

    def test_launch_failure_has_a_result_before_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Evidence(directory, lambda data: len(data))
            result = run_native(['/nonexistent/sargo-native-probe'], directory, evidence)
            evidence.close()
            self.assertIsNone(result['returncode'])
            self.assertIn('launch_error', result)
            self.assertTrue((Path(directory) / 'native-result.json').exists())
            self.assertFalse(completed_sequence(result))

    def test_zero_exit_without_operation_evidence_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Evidence(directory, lambda data: len(data))
            result = run_native([sys.executable, '-c', 'pass'], directory, evidence)
            evidence.close()
            self.assertEqual(result['returncode'], 0)
            self.assertFalse(completed_sequence(result))


if __name__ == '__main__':
    unittest.main()
