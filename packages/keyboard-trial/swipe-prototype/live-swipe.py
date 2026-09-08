#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt in to a source-built, unsigned swipe prototype until the next reboot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
SCHEMAS = Path("/usr/share/glib-2.0/schemas")
SCHEMA = "mobi.phosh.osk.gschema.xml"
OVERRIDE = "99-pocketfed-live-swipe.gschema.override"
OVERRIDE_BYTES = b"[mobi.phosh.osk]\nswipe-typing=true\n"
OSK = "mobi.phosh.OSK.service"
DICT = "org.verbisage.Dictionary"
STABLE = {
    "phosh-osk-stevia": ("5cdb5ee1c3c797ec917229d6394266b8e516102b9455f0119c1a86630ab4cd86", "4b069e86ad0da12ef24b9cefefe842a7b5b52b4deec7148ca1747b2a80d26f7d"),
    "verbisaged": ("57100df11fd65d3c7a170876cf08c05019f27356f2594b185ea96e4e9a7351b0", "9cc583d68a5dc3c7077c2282f30f23289208a99a0440fdf228deb0037c9b2b0e"),
    "verbisage": ("4c7c63c2995dfb8f34d8d48c4569071f5d74548c93ea14dd353439a822b70b88", "5a648fdc5cd43e0b762f660d1d34ca2e27c9baf4100522271ef946731df66494"),
    SCHEMA: ("7c0efb72c726538f9a592e133bfa4e6a184a4e438f2cc15e780da06a24f43111",),
}
TARGETS = {name: Path("/usr/bin") / name for name in STABLE if name != SCHEMA}
TARGETS[SCHEMA] = SCHEMAS / SCHEMA
DEPLOYMENT_FIELDS = (
    "id", "checksum", "serial", "osname", "booted", "staged", "pinned",
    "base-checksum", "container-image-reference", "origin", "requested-packages",
    "requested-base-removals", "base-removals", "regenerate-initramfs", "initramfs-args",
    "requested-local-fileoverride-packages", "requested-base-remote-replacements",
    "base-remote-replacements", "requested-base-local-replacements", "requested-local-packages",
    "base-local-replacements", "live-inprogress", "live-replaced",
)


def run(argv, **kwargs):
    print("+ " + " ".join(map(str, argv)), flush=True)
    return subprocess.check_output(list(map(str, argv)), text=True, **kwargs).strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Expected a regular, nonsymlink file: " + str(path))
    return path.read_bytes()


def load_payload(manifest, expected=None):
    raw = read_regular(manifest)
    if expected is not None and sha(raw) != expected:
        raise ValueError("Manifest changed after preflight")
    doc = json.loads(raw)
    if not isinstance(doc, dict) or doc.get("format") != 1 or doc.get("architecture") != "aarch64" or not isinstance(doc.get("files"), dict) or set(doc["files"]) != set(TARGETS):
        raise ValueError("Manifest must name exactly the three aarch64 binaries and OSK schema")
    payload = {}
    for name, item in doc["files"].items():
        if not isinstance(item, dict) or set(item) != {"sha256"}:
            raise ValueError("Each manifest file must contain only its SHA256: " + name)
        checksum = item["sha256"]
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Invalid payload digest: " + name)
        data = read_regular(Path(manifest).parent / "payload" / name)
        if sha(data) != checksum:
            raise ValueError("Payload digest mismatch: " + name)
        if name != SCHEMA and (data[:6] != b"\x7fELF\x02\x01" or data[18:20] != b"\xb7\x00"):
            raise ValueError("Payload is not a little-endian aarch64 ELF executable: " + name)
        payload[name] = data
    return payload, sha(raw)


def validate_targets(payload):
    for name, target in TARGETS.items():
        if sha(read_regular(target)) not in (*STABLE[name], sha(payload[name])):
            raise ValueError("Unexpected existing file; preserve the other experiment: " + str(target))
    override = SCHEMAS / OVERRIDE
    if override.exists() or override.is_symlink():
        if read_regular(override) != OVERRIDE_BYTES:
            raise ValueError("An unrelated live swipe schema override already exists")
    read_regular(SCHEMAS / "gschemas.compiled")


def deployment_state():
    snapshot = json.loads(run(["rpm-ostree", "status", "--json"]))
    if snapshot.get("transaction"):
        raise ValueError("An rpm-ostree transaction is active; retry after it finishes")
    deployed = snapshot.get("deployments", [])
    current = [d for d in deployed if d.get("booted")]
    if len(current) != 1:
        raise ValueError("Expected one booted deployment")
    stable = [{key: d.get(key) for key in DEPLOYMENT_FIELDS} for d in deployed]
    fingerprint = sha(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode())
    return fingerprint, current[0].get("unlocked", "none")


def same_deployment(expected):
    actual, _ = deployment_state()
    if actual != expected:
        raise ValueError("Deployment identity, staging, pins or package requests changed during this run")


def require_overlay():
    for directory in (Path("/usr"), Path("/usr/bin"), SCHEMAS):
        kind = run(["stat", "--file-system", "--format=%T", directory])
        if kind != "overlayfs" or os.statvfs(directory).f_flag & os.ST_RDONLY:
            raise ValueError("Expected the visible writable /usr overlay at " + str(directory))
        if directory.stat().st_dev != Path("/usr").stat().st_dev:
            raise ValueError("Unexpected nested filesystem below /usr: " + str(directory))


def compile_schema(payload):
    # Compile every installed schema with the one reviewed XML replacement and
    # our default override before changing any active file.
    with tempfile.TemporaryDirectory(prefix=".live-swipe-schema-", dir=SCHEMAS) as temporary:
        staged = Path(temporary)
        for source in SCHEMAS.iterdir():
            if source.name.endswith((".xml", ".gschema.override")):
                (staged / source.name).write_bytes(read_regular(source))
        (staged / SCHEMA).write_bytes(payload[SCHEMA])
        (staged / OVERRIDE).write_bytes(OVERRIDE_BYTES)
        run(["glib-compile-schemas", "--strict", staged])
        enabled = run(["gsettings", "--schemadir", staged, "get", "mobi.phosh.osk", "swipe-typing"],
                      env={**os.environ, "GSETTINGS_BACKEND": "memory"})
        if enabled != "true":
            raise ValueError("The temporary schema default did not enable swipe typing")
        return read_regular(staged / "gschemas.compiled")


def replace_files(contents):
    originals = {path: read_regular(path) if path.exists() else None for path in contents}
    prepared, replaced = [], []

    def prepare(target, data):
        fd, name = tempfile.mkstemp(prefix=".live-swipe-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o755 if target.name in STABLE and target.name != SCHEMA else 0o644)
                os.fchown(stream.fileno(), 0, 0)
                os.fsync(stream.fileno())
            reference = target if target.exists() else SCHEMAS / SCHEMA
            run(["chcon", "--reference=" + str(reference), temporary])
            return temporary
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    try:
        for target, data in contents.items():
            prepared.append((prepare(target, data), target))
        for temporary, target in prepared:
            os.replace(temporary, target)
            replaced.append(target)
            run(["restorecon", "-F", target])
        for directory in {path.parent for path in contents}:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except BaseException:
        # Running services still hold their old inodes. Restore complete on-disk
        # inputs if any rename or relabel fails, including a newly added override.
        for target in reversed(replaced):
            if originals[target] is None:
                target.unlink(missing_ok=True)
            else:
                temporary = prepare(target, originals[target])
                try:
                    os.replace(temporary, target)
                    run(["restorecon", "-F", target])
                finally:
                    temporary.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _ in prepared:
            temporary.unlink(missing_ok=True)


def write_usr(manifest, manifest_hash, fingerprint):
    if os.geteuid() != 0 or os.uname().machine != "aarch64":
        raise ValueError("The internal writer requires sudo on aarch64")
    if not manifest_hash or not fingerprint:
        raise ValueError("Run apply as the Phosh user first")
    payload, _ = load_payload(manifest, manifest_hash)
    validate_targets(payload)
    same_deployment(fingerprint)
    _, unlocked = deployment_state()
    if unlocked == "none":
        run(["rpm-ostree", "usroverlay"])
    elif unlocked != "development":
        raise ValueError("Only an ephemeral development unlock is supported; hotfix is refused")
    require_overlay()
    same_deployment(fingerprint)
    compiled = compile_schema(payload)
    contents = {TARGETS[name]: data for name, data in payload.items()}
    contents[SCHEMAS / OVERRIDE] = OVERRIDE_BYTES
    contents[SCHEMAS / "gschemas.compiled"] = compiled
    replace_files(contents)
    for target, data in contents.items():
        if read_regular(target) != data:
            raise ValueError("Installed bytes differ from the prepared payload: " + str(target))
    same_deployment(fingerprint)
    print("Applied unsigned source-built prototype in ephemeral /usr; saved settings and deployments preserved.")


def bus_pid(name):
    call = ["gdbus", "call", "--session", "--timeout", "5", "--dest", "org.freedesktop.DBus",
            "--object-path", "/org/freedesktop/DBus", "--method"]
    if run([*call, "org.freedesktop.DBus.NameHasOwner", name]) != "(true,)":
        return None
    reply = run([*call, "org.freedesktop.DBus.GetConnectionUnixProcessID", name])
    match = re.fullmatch(r"\(uint32 (\d+),\)", reply)
    if not match:
        raise ValueError("Unexpected bus PID reply")
    return int(match[1])


def require_process(pid, binary, allowed):
    if not pid or Path(f"/proc/{pid}").stat().st_uid != os.getuid() or sha(Path(f"/proc/{pid}/exe").read_bytes()) not in allowed:
        raise ValueError("Unexpected owner or executable for " + binary)


def service(bus, binary, payload, required=False):
    pid = bus_pid(bus)
    if pid is None:
        if required:
            raise ValueError("The keyboard service is not running")
        return None
    require_process(pid, binary, (*STABLE[binary], sha(payload[binary])))
    unit = OSK if bus == "sm.puri.OSK0" else Path(f"/proc/{pid}/cgroup").read_text().strip().rsplit("/", 1)[-1]
    if (bus != "sm.puri.OSK0" and (not unit.endswith(".service") or DICT not in unit)) or run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"]) != str(pid):
        raise ValueError("The bus owner does not match the expected user service")
    return unit


def activate(manifest):
    if os.geteuid() == 0 or os.uname().machine != "aarch64":
        raise ValueError("Run apply as the normal Phosh user on aarch64; sudo is used only for /usr")
    payload, manifest_hash = load_payload(manifest)
    validate_targets(payload)
    fingerprint, unlocked = deployment_state()
    if unlocked not in ("none", "development"):
        raise ValueError("The current unlock is not an ephemeral development overlay")
    service("sm.puri.OSK0", "phosh-osk-stevia", payload, required=True)
    service(DICT, "verbisaged", payload)
    print("Opting in to an unsigned, source-built swipe prototype. Reboot restores deployed files.")
    run(["sudo", sys.executable, Path(__file__).resolve(), "--write-usr", "--manifest", manifest,
         "--manifest-sha256", manifest_hash, "--deployment-fingerprint", fingerprint])
    try:
        run(["systemctl", "--user", "stop", OSK])
        unit = service(DICT, "verbisaged", payload)
        if unit:
            run(["systemctl", "--user", "stop", unit])
        call = ["gdbus", "call", "--session", "--timeout", "5", "--dest", DICT,
                "--object-path", "/org/verbisage/Dictionary", "--method"]
        reply = run([*call, "org.verbisage.Dictionary1.Complete", "helo", "6", "en_US"])
        if not re.match(r"^\(\[\('hello',", reply):
            raise ValueError("Expected hello first from Complete: " + reply)
        run([*call, "org.verbisage.Dictionary1.RecognizeSwipe",
             "[(10.0, 10.0, uint32 0), (50.0, 10.0, uint32 100)]",
             "[('a', 0.0, 0.0, 20.0, 20.0), ('b', 40.0, 0.0, 20.0, 20.0)]", "6", "en_US"])
    finally:
        run(["systemctl", "--user", "start", OSK])
    pid = None
    for _ in range(25):
        pid = bus_pid("sm.puri.OSK0")
        if pid:
            break
        time.sleep(.1)
    require_process(pid, "phosh-osk-stevia", (sha(payload["phosh-osk-stevia"]),))
    require_process(bus_pid(DICT), "verbisaged", (sha(payload["verbisaged"]),))
    same_deployment(fingerprint)
    enabled = run(["gsettings", "get", "mobi.phosh.osk", "swipe-typing"])
    if enabled != "true":
        raise ValueError("An existing user setting overrides the temporary swipe default; it was preserved")
    print("PASS: prototype processes and swipe service verified; swipe enabled until reboot.")
    print("No dconf values changed. Any staged image remains staged; reboot will boot that image normally.")


def status(manifest):
    payload, _ = load_payload(manifest)
    fingerprint, unlocked = deployment_state()
    print("Source-built unsigned prototype; this is not a COPR package installation.")
    print("Unlock: " + unlocked + "; deployment fingerprint: " + fingerprint)
    for name, target in TARGETS.items():
        actual = sha(read_regular(target))
        label = "prototype" if actual == sha(payload[name]) else "stable 1.1/1.2" if actual in STABLE[name] else "other bytes"
        print(name + ": " + label)
    for bus, binary in (("sm.puri.OSK0", "phosh-osk-stevia"), (DICT, "verbisaged")):
        pid = bus_pid(bus)
        actual = sha(Path(f"/proc/{pid}/exe").read_bytes()) if pid else None
        label = "prototype" if actual == sha(payload[binary]) else "stable 1.1/1.2" if actual in STABLE[binary] else "not running or other bytes"
        print(binary + " running: " + label)
    print("No keyboard services activated or settings changed by status.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("verify", "status", "apply"), default="status")
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    parser.add_argument("--write-usr", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--manifest-sha256", help=argparse.SUPPRESS)
    parser.add_argument("--deployment-fingerprint", help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = args.manifest.resolve()
    if args.write_usr:
        write_usr(manifest, args.manifest_sha256, args.deployment_fingerprint)
    elif args.action == "apply":
        activate(manifest)
    elif args.action == "verify":
        payload, checksum = load_payload(manifest)
        print(f"Verified {len(payload)} source-built unsigned payload files; manifest SHA256 {checksum}")
    else:
        status(manifest)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print("STOP: " + str(error), file=sys.stderr)
        print("Reboot discards the /usr overlay and boots the normal default deployment. Saved keyboard preferences are untouched.", file=sys.stderr)
        raise SystemExit(1)
