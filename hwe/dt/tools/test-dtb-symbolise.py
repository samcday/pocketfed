#!/usr/bin/env python3
"""Host-only checks for dtb-symbolise.py using tiny synthetic DTS inputs."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import libfdt


spec = importlib.util.spec_from_file_location(
    "dtb_symbolise", Path(__file__).with_name("dtb-symbolise.py"))
symbolise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symbolise)


BASE_DTS = """/dts-v1/;

/ {
	#address-cells = <1>;
	#size-cells = <1>;

	intc: interrupt-controller@1000 {
		compatible = "test,intc";
		reg = <0x1000 0x100>;
		interrupt-controller;
		#interrupt-cells = <1>;
	};

	dev: dev@2000 {
		compatible = "test,dev";
		reg = <0x2000 0x100>;
		interrupts-extended = <&intc 3>;
	};

	extra: extra@3000 {
		compatible = "test,extra";
		reg = <0x3000 0x100>;
	};
};
"""


def compile_dts(text, output, symbols):
    source = output.with_suffix(".dts")
    source.write_text(text)
    argv = ["dtc", "-I", "dts", "-O", "dtb", "-b", "0"]
    if symbols:
        argv.append("-@")
    argv += ["-o", str(output), str(source)]
    subprocess.run(argv, check=True, capture_output=True, text=True)
    return output


class EquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.reference = compile_dts(BASE_DTS, self.base / "reference.dtb", True)
        self.plain = compile_dts(BASE_DTS, self.base / "plain.dtb", False)

    def test_labels_symbols_and_phandles_are_normalised_away(self):
        self.assertEqual(symbolise.normalize(symbolise.decompile(self.plain, "dtc", [])),
                         symbolise.normalize(symbolise.decompile(self.reference, "dtc", [])))
        passed, diff, _log = symbolise.equivalence(self.plain, self.reference, "dtc")
        self.assertTrue(passed, diff)

    def test_a_real_tree_difference_fails_the_gate(self):
        changed = compile_dts(BASE_DTS.replace('compatible = "test,dev";',
                                               'compatible = "test,dev";\n\t\ttest-property;'),
                              self.base / "changed.dtb", True)
        passed, diff, _log = symbolise.equivalence(self.plain, changed, "dtc")
        self.assertFalse(passed)
        self.assertIn("test-property", diff)


class InjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.reference = compile_dts(BASE_DTS, self.base / "reference.dtb", True)
        self.plain = compile_dts(BASE_DTS, self.base / "plain.dtb", False)

    def test_reads_symbols_and_allocates_only_missing_phandles(self):
        symbols = dict(symbolise.read_symbols(self.reference))
        self.assertEqual(symbols, {
            "intc": "/interrupt-controller@1000",
            "dev": "/dev@2000",
            "extra": "/extra@3000",
        })
        plain = libfdt.Fdt(self.plain.read_bytes())
        existing = plain.getprop(plain.path_offset("/interrupt-controller@1000"), "phandle").as_uint32()
        result, added = symbolise.inject_symbols(
            self.plain.read_bytes(), list(symbols.items()))
        injected = libfdt.Fdt(result)
        self.assertEqual(injected.getprop(injected.path_offset("/interrupt-controller@1000"),
                                          "phandle").as_uint32(), existing)
        self.assertEqual({entry["label"] for entry in added}, {"dev", "extra"})
        self.assertEqual([entry["phandle"] for entry in added], sorted(
            entry["phandle"] for entry in added))
        self.assertTrue(all(entry["phandle"] > existing for entry in added))
        self.assertEqual(injected.getprop(injected.path_offset("/dev@2000"), "phandle").as_uint32(),
                         added[0]["phandle"])
        self.assertEqual(injected.getprop(injected.path_offset("/__symbols__"), "extra").as_str(),
                         "/extra@3000")

    def test_rejects_a_symbol_path_absent_from_the_base(self):
        with self.assertRaisesRegex(symbolise.SymboliseError, "absent from the base"):
            symbolise.inject_symbols(self.plain.read_bytes(), [("ghost", "/no/such/node")])


if __name__ == "__main__":
    unittest.main()
