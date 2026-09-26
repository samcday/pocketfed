#!/usr/bin/env python3
"""Host-only checks for patch-dtb.py using a tiny synthetic kernel tree."""

import difflib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).with_name("patch-dtb.py")
spec = importlib.util.spec_from_file_location("patch_dtb", TOOL)
patch_dtb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch_dtb)


HEADER = "#define TEST_IRQ 3\n"

SOC_DTSI = """/ {
\t#address-cells = <1>;
\t#size-cells = <1>;

\tintc: interrupt-controller@1000 {
\t\tcompatible = "test,intc";
\t\treg = <0x1000 0x100>;
\t\tinterrupt-controller;
\t\t#interrupt-cells = <1>;
\t};

\tuart: serial@2000 {
\t\tcompatible = "test,uart";
\t\treg = <0x2000 0x100>;
\t\tinterrupts-extended = <&intc TEST_IRQ>;
\t\tstatus = "disabled";
\t};
};
"""

BOARD_DTS = """/dts-v1/;

#include <dt-bindings/test.h>
#include "soc.dtsi"

/ {
\tmodel = "Test board";
};
"""

UART_ENABLED = SOC_DTSI.replace('\t\tstatus = "disabled";\n', '\t\tstatus = "okay";\n')


def unified(path, old, new):
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        f"a/{path}", f"b/{path}"))


class PatchDtbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.tree = root / "tree"
        self.dts_dir = self.tree / "arch/arm64/boot/dts/test"
        self.dts_dir.mkdir(parents=True)
        (self.dts_dir / "soc.dtsi").write_text(SOC_DTSI)
        (self.dts_dir / "board.dts").write_text(BOARD_DTS)
        self.include = root / "include"
        (self.include / "dt-bindings").mkdir(parents=True)
        (self.include / "dt-bindings/test.h").write_text(HEADER)
        self.base = root / "base.dtb"
        patch_dtb.compile_dtb(self.tree, self.include, "test/board.dts", self.base, "cpp", "dtc")
        self.series_dir = root / "series"
        self.series_dir.mkdir()
        self.output = root / "out/board.dtb"
        self.report = root / "report.json"

    def write_series(self, patches):
        lines = ["# test series"]
        for name, text in patches:
            (self.series_dir / name).write_text(text)
            lines.append(name)
        series = self.series_dir / "series"
        series.write_text("\n".join(lines) + "\n")
        return series

    def run_tool(self, series):
        series = series.relative_to(self.series_dir.parent)
        return subprocess.run(
            [sys.executable, str(TOOL), "--base", str(self.base), "--kernel-tree", str(self.tree),
             "--include", str(self.include), "--dts", "test/board.dts", "--series", str(series),
             "--output", str(self.output), "--report", str(self.report), "--source-tag", "kernel-test.1"],
            capture_output=True, text=True, cwd=self.series_dir.parent)

    def test_series_is_applied_on_top_of_the_base(self):
        series = self.write_series([("enable-uart.patch", unified(
            "arch/arm64/boot/dts/test/soc.dtsi", SOC_DTSI, UART_ENABLED))])
        result = self.run_tool(series)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = subprocess.run(["fdtget", str(self.output), "/serial@2000", "status"],
                                capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(status, "okay")
        report = json.loads(self.report.read_text())
        self.assertEqual(report["source_tag"], "kernel-test.1")
        self.assertEqual([p["name"] for p in report["patches"]], ["enable-uart.patch"])
        self.assertNotEqual(report["output_sha256"], report["base_sha256"])
        nodes = subprocess.run(["fdtget", "-l", str(self.output), "/"],
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertNotIn("__symbols__", nodes)
        # The kernel tree itself is never modified.
        self.assertEqual((self.dts_dir / "soc.dtsi").read_text(), SOC_DTSI)

    def test_base_mismatch_is_refused(self):
        (self.dts_dir / "board.dts").write_text(BOARD_DTS.replace("Test board", "Other board"))
        series = self.write_series([])
        result = self.run_tool(series)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not compile to Fedora's blob", result.stderr)
        self.assertIn("Other board", result.stderr)
        self.assertFalse(self.output.exists())

    def test_patch_already_upstream_says_drop_it(self):
        (self.dts_dir / "soc.dtsi").write_text(UART_ENABLED)
        patch_dtb.compile_dtb(self.tree, self.include, "test/board.dts", self.base, "cpp", "dtc")
        series = self.write_series([("enable-uart.patch", unified(
            "arch/arm64/boot/dts/test/soc.dtsi", SOC_DTSI, UART_ENABLED))])
        result = self.run_tool(series)
        self.assertEqual(result.returncode, 1)
        self.assertIn("already applied in kernel-test.1", result.stderr)
        self.assertIn("drop it from the series", result.stderr)
        self.assertFalse(self.output.exists())

    def test_stale_patch_asks_for_a_refresh(self):
        drifted = SOC_DTSI.replace("0x2000 0x100", "0x2000 0x200")
        series = self.write_series([("enable-uart.patch", unified(
            "arch/arm64/boot/dts/test/soc.dtsi", drifted,
            drifted.replace('"disabled"', '"okay"')))])
        result = self.run_tool(series)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not apply to kernel-test.1", result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_patch_is_named(self):
        series = self.series_dir / "series"
        series.write_text("absent.patch\n")
        result = self.run_tool(series)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no such patch", result.stderr)


if __name__ == "__main__":
    unittest.main()
