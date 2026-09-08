#!/usr/bin/env python3
"""Check packaged Flatpak startup callbacks against delayed PID metadata.

Requires Python 3, a C compiler, pkg-config and GLib/GIO development files.
The baseline comes from the pinned upstream Flatpak 1.19.0 release archive;
the candidate comes directly from the RPM's prepared production source tree.
No services or installed Flatpak files are modified.
"""

import argparse
import hashlib
import os
from pathlib import Path
import resource
import shlex
import subprocess
import tarfile
import tempfile


ARCHIVE_SHA256 = "329f9e605a5e61b79444f7406e0ed90a31f6349cf41e8d5f4c1d4c82cb66356d"
SOURCE_SHA256 = {
    "portal/flatpak-portal.c": "38c6d210d1cc25569c887c0e18261d1f4905e444c1a014e48e57c64449a5794f",
    "common/flatpak-instance.c": "b18e3f0c8eaee2b3744758133f47b1fbd866f6a6495012ffb6a0447451bdac7c",
}


def extract_between(source, start, end):
    return source[source.index(start):source.index(end)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_archive", type=Path)
    parser.add_argument("--prepared-source", type=Path, required=True)
    args = parser.parse_args()
    if hashlib.sha256(args.source_archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        parser.error("source archive is not the pinned Flatpak 1.19.0 release")

    package_dir = Path(__file__).resolve().parent
    template = (package_dir / "test-start-notification.c.in").read_text()
    baseline = {}
    with tarfile.open(args.source_archive, "r:xz") as archive:
        for name, digest in SOURCE_SHA256.items():
            data = archive.extractfile(f"flatpak-1.19.0/{name}").read()
            if hashlib.sha256(data).hexdigest() != digest:
                parser.error(f"unexpected baseline source content: {name}")
            baseline[name] = data.decode()
    prepared = {
        name: (args.prepared_source / name).read_text()
        for name in SOURCE_SHA256
    }
    compiler = shlex.split(os.environ.get("CC", "cc"))
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "glib-2.0", "gio-2.0"], text=True
    ))
    # The negative control intentionally aborts on the unmet signal assertion.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    with tempfile.TemporaryDirectory(prefix="flatpak-start-notification-") as work:
        work = Path(work)
        for label, source, is_patched in [
            ("baseline", baseline, 0),
            ("prepared", prepared, 1),
        ]:
            get_pid = extract_between(
                source["common/flatpak-instance.c"],
                "static int\nget_pid (",
                "\nFlatpakInstance *\nflatpak_instance_new (",
            )
            callbacks = extract_between(
                source["portal/flatpak-portal.c"],
                "typedef struct\n{\n  guint pid;\n  gchar buffer",
                "\nstatic void\ndrop_cloexec (",
            )
            harness = template.replace("@GET_PID@", get_pid).replace(
                "@PORTAL_CALLBACKS@", callbacks
            )
            c_path = work / f"{label}.c"
            executable = work / label
            c_path.write_text(harness)
            subprocess.run([
                *compiler, f"-DPATCHED={is_patched}",
                "-Werror=implicit-function-declaration", "-o", str(executable),
                str(c_path), *flags,
            ], check=True)
            print(f"Testing {label} production callbacks", flush=True)
            subprocess.run([str(executable)], check=True, timeout=15)
            oracle = subprocess.run(
                [str(executable), "--require-delayed-pid-notification"],
                capture_output=True, text=True, timeout=5,
            )
            if is_patched:
                if oracle.returncode != 0:
                    raise RuntimeError(oracle.stdout + oracle.stderr)
                print(oracle.stdout.strip(), flush=True)
            else:
                if oracle.returncode == 0 or "signals == expected_signals" not in oracle.stdout + oracle.stderr:
                    raise RuntimeError("baseline did not reproduce the missing startup signal\n" + oracle.stdout + oracle.stderr)
                print("PASS negative control: unpatched callback fails the same required-notification assertion", flush=True)


if __name__ == "__main__":
    main()
