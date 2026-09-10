#!/usr/bin/env python3
"""Compile the actual auth.c and verify the fix plus its unpatched control."""

import argparse
import os
from pathlib import Path
import resource
import shlex
import subprocess
import tarfile
import tempfile


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=60, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with tempfile.TemporaryDirectory(prefix="phosh-auth-") as tmp:
        root = Path(tmp)
        with tarfile.open(args.archive) as archive:
            archive.extractall(root, filter="data")
        source = root / "phosh-v0.57.0"
        original = root / "auth-original.c"
        original.write_bytes((source / "src/auth.c").read_bytes())
        with (package / "0001-auth-do-not-replay-a-rejected-token.patch").open() as patch:
            run("patch", "-p1", cwd=source, stdin=patch)
        (root / "phosh-config.h").touch()
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True))
        for name, candidate in (("patched", source / "src/auth.c"), ("original", original)):
            binary = root / name
            run(os.environ.get("CC", "cc"), "-g", "-Wall", "-Wextra", "-Werror",
                "-Wno-unused-parameter", f"-I{root}", f"-I{source / 'src'}",
                str(candidate), str(source / "tests/test-auth.c"), *flags,
                "-o", str(binary))
            if name == "patched":
                run(str(binary))
            else:
                result = subprocess.run([str(binary), "-p", "/phosh/auth/homed-retry"],
                                        capture_output=True, text=True, timeout=60)
                output = result.stdout + result.stderr
                if result.returncode == 0 or "(4 == 1)" not in output:
                    raise RuntimeError(f"Unexpected negative control result:\n{output}")
                print("PASS: unpatched auth.c fails with four checks instead of one")


if __name__ == "__main__":
    main()
