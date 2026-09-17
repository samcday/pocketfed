#!/usr/bin/env python3
"""Exercise the graphical-acceptance CPU collector against stub workloads.

The collector runs two static aarch64 binaries in the guest; these tests replace
them with tiny shells that emit the same machine-readable output, then check the
collector's parsing, JSON summary, console marker and exit status. This verifies
the acceptance logic itself rather than restating configuration.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / "acceptance/apq8016-sbc/usr/libexec/pocketfed-liveboot-cpu-acceptance"
WORK_HEADER = "SMP_WORK_V2 expected=292d74d0d0222325 bytes_per_cpu=67108864"
WORK_PASS = "SMP_WORK_PASS all_four_cpus"
COHERENCY_PASS = "SMP_COHERENCY_PASS all_four_cpus_shared_memory_and_migration"


def work_output(cpus=(0, 1, 2, 3), seconds=0.5, digest="292d74d0d0222325", verdict="PASS"):
    lines = [WORK_HEADER]
    for cpu in cpus:
        lines.append(f"cpu={cpu} start_cpu={cpu} end_cpu={cpu} hash={digest} "
                     f"cpu_seconds={seconds} {verdict}")
    lines.append(WORK_PASS if verdict == "PASS" else "SMP_WORK_FAIL")
    return "\n".join(lines) + "\n"


def coherency_output(passed=True):
    return COHERENCY_PASS + "\n" if passed else "SMP_COHERENCY_FAIL\n"


class CpuAcceptanceTests(unittest.TestCase):
    def collect(self, work, coherency):
        work_text, work_code = work
        coh_text, coh_code = coherency
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, (text, code) in {"smp-work": (work_text, work_code),
                                       "smp-coherency": (coh_text, coh_code)}.items():
                stub = root / name
                stub.write_text(f"#!/bin/sh\ncat <<'EOF'\n{text}EOF\nexit {code}\n")
                stub.chmod(0o755)
            output = root / "cpu-acceptance.json"
            completed = subprocess.run(
                [str(COLLECTOR), "--workload-dir", str(root), "--output", str(output)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
            return completed, json.loads(output.read_text())

    def test_all_four_cpus_and_coherency_pass(self):
        completed, result = self.collect((work_output(), 0), (coherency_output(), 0))
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(result["result"], "pass")
        self.assertTrue(result["work"]["complete"])
        self.assertTrue(result["coherency"]["complete"])
        self.assertEqual(sorted(result["work"]["cpus"]), ["0", "1", "2", "3"])
        self.assertIn("POCKETFED_CPU_ACCEPTANCE=", completed.stdout)
        marker = [line for line in completed.stdout.splitlines()
                  if line.startswith("POCKETFED_CPU_ACCEPTANCE=")][0]
        self.assertEqual(json.loads(marker.split("=", 1)[1])["result"], "pass")

    def test_incomplete_cpu_set_is_a_failure(self):
        for cpus in ((0, 1, 2), (0, 0, 1, 2)):
            with self.subTest(cpus=cpus):
                completed, result = self.collect((work_output(cpus=cpus), 0), (coherency_output(), 0))
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(result["result"], "fail")
                self.assertFalse(result["work"]["complete"])

    def test_short_or_wrong_cpu_result_is_a_failure(self):
        cases = {"too_short": work_output(seconds=0.001),
                 "wrong_hash": work_output(digest="0000000000000000"),
                 "failed_line": work_output(verdict="FAIL")}
        for name, output in cases.items():
            with self.subTest(name=name):
                code = 0 if output.endswith(WORK_PASS + "\n") else 1
                completed, result = self.collect((output, code), (coherency_output(), 0))
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(result["result"], "fail")

    def test_failed_coherency_is_a_failure(self):
        completed, result = self.collect((work_output(), 0), (coherency_output(False), 1))
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(result["result"], "fail")
        self.assertTrue(result["work"]["complete"])
        self.assertFalse(result["coherency"]["complete"])


if __name__ == "__main__":
    unittest.main()
