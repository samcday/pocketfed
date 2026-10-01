#!/usr/bin/env python3
"""Compile actual driver lifecycle functions against a fault-injecting PM/I2C shim.

Usage: test-lc898219xi.py /path/to/linux
The shim checks ordering and reference accounting; it cannot verify hardware.
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


FUNCTIONS = (
    "sd_to_lc898219xi",
    "lc898219xi_set_dac",
    "lc898219xi_power_on",
    "lc898219xi_power_off",
    "lc898219xi_runtime_suspend",
    "lc898219xi_runtime_resume",
    "lc898219xi_set_ctrl",
    "lc898219xi_open",
    "lc898219xi_close",
)


def function(source, name):
    match = re.search(
        r"^static [^;{}]*\b" + re.escape(name) + r"\([^;{}]*\)\n\{.*?^\}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise ValueError(f"Cannot extract production function {name}")
    return match.group()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    args = parser.parse_args()
    source = (args.kernel / "drivers/media/i2c/lc898219xi.c").read_text()
    definitions = source[source.index("#define LC898219XI_NAME") : source.index("static inline")]
    fixture = Path(__file__).with_name("lc898219xi-fixture.c").read_text()
    production = definitions + "\n" + "\n\n".join(function(source, name) for name in FUNCTIONS)
    test_source = fixture.replace("/* PRODUCTION_DRIVER_FUNCTIONS */", production)
    with tempfile.TemporaryDirectory(prefix="lc898219xi-test-") as work:
        test_file = Path(work) / "lifecycle.c"
        executable = Path(work) / "lifecycle"
        test_file.write_text(test_source)
        subprocess.run(
            [os.environ.get("CC", "cc"), "-std=gnu11", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter", "-fsanitize=undefined",
             "-fsanitize-undefined-trap-on-error", "-g", str(test_file),
             "-o", str(executable)],
            check=True,
            env={**os.environ, "CCACHE_DISABLE": "1"},
        )
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
