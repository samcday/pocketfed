#!/usr/bin/env python3
"""Host-only checks for compose-dtb.py using tiny synthetic DTS inputs."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compose = load("compose_dtb", Path(__file__).with_name("compose-dtb.py"))
symbolise = load("dtb_symbolise", Path(__file__).with_name("dtb-symbolise.py"))


BASE_DTS = """/dts-v1/;

/ {
	#address-cells = <2>;
	#size-cells = <2>;

	aliases { };

	soc@0 {
		#address-cells = <2>;
		#size-cells = <2>;
		ranges;

		qupv3_id_1: geniqup@ac0000 {
			compatible = "test,qup";
			reg = <0 0xac0000 0 0x6000>;
			status = "okay";
		};
	};
};
"""

OVERLAY_DTS = """/dts-v1/;
/plugin/;

&qupv3_id_1 {
	serial@a90000 {
		compatible = "test,geni-debug-uart";
		status = "okay";
	};
};

&{/aliases} {
	serial0 = "/soc@0/geniqup@ac0000/serial@a90000";
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


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base_dir = Path(self.tmp.name)
        self.base = compile_dts(BASE_DTS, self.base_dir / "base.dtb", False)
        self.reference = compile_dts(BASE_DTS, self.base_dir / "reference.dtb", True)
        symbols = symbolise.read_symbols(self.reference)
        self.symbolised = self.base_dir / "symbolised.dtb"
        self.symbolised.write_bytes(symbolise.inject_symbols(self.base.read_bytes(), symbols)[0])

    def args(self, overlay, output, sidecar):
        return argparse.Namespace(base=self.base, symbolised=self.symbolised, overlay=[overlay],
                                  output=output, sidecar=sidecar, symbolise_report=None,
                                  dtc="dtc", fdtoverlay="fdtoverlay", fdtget="fdtget")

    def test_applies_overlay_and_sets_alias(self):
        overlay = compile_dts(OVERLAY_DTS, self.base_dir / "debug-uart.dtbo", True)
        output = self.base_dir / "final.dtb"
        sidecar = self.base_dir / "sidecar.json"
        result = compose.compose(self.args(overlay, output, sidecar))
        self.assertEqual(result, output)
        record = json.loads(sidecar.read_text())
        self.assertTrue(all(check["pass"] for check in record["fdtget"]))
        self.assertTrue(record["round_trip"])
        self.assertEqual(record["base"]["sha256"], compose.sha256(self.base))
        self.assertEqual(record["output"]["sha256"], compose.sha256(output))
        self.assertIn("serial@a90000", record["diff_vs_symbolised"])
        self.assertIn("serial0", record["diff_vs_symbolised"])

    def test_rejects_an_unresolvable_target(self):
        overlay = compile_dts("/dts-v1/;\n/plugin/;\n&missing_label { status = \"okay\"; };\n",
                              self.base_dir / "missing.dtbo", True)
        with self.assertRaisesRegex(compose.ComposeError, "command failed"):
            compose.compose(self.args(overlay, self.base_dir / "final.dtb",
                                      self.base_dir / "sidecar.json"))


if __name__ == "__main__":
    unittest.main()
