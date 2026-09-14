#!/usr/bin/env python3
"""Prepare a recorded kboop run, then optionally host it with UART capture."""
import argparse
import contextlib
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import stat
import tempfile
import subprocess
import termios
import time


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
        raise ValueError("serial/run name must contain only letters, digits, dot, underscore or dash")
    return value


def early_modules(recipe, repo):
    config = (repo / recipe["dracut_config"]).read_text()
    groups = re.findall(r'(?:force_drivers|add_drivers)\+="(.*?)"', config, re.S)
    modules = " ".join(groups).replace("\\", " ").split()
    return list(dict.fromkeys(modules))


def verify_required_modules(bundle, requested):
    install = bundle.parent / json.loads(bundle.read_text())["modules_install"]
    releases = list((install / "lib/modules").iterdir())
    if len(releases) != 1:
        raise ValueError("expected exactly one modules release")
    release = releases[0]
    names = {p.name.split(".ko")[0].replace("-", "_")
             for p in release.rglob("*.ko*") if p.is_file()}
    for line in (release / "modules.builtin").read_text().splitlines():
        names.add(Path(line).name.split(".ko")[0].replace("-", "_"))
    required = [*requested, "configfs", "libcomposite", "usb_f_fs", "ublk_drv", "erofs", "overlay"]
    missing = [name for name in required if name.replace("-", "_") not in names]
    if missing:
        raise ValueError("required early modules are neither installed nor built in: " + ", ".join(missing))


def verify_fixture(fixture):
    spec = importlib.util.spec_from_file_location("liveboot_fixture", Path(__file__).with_name("prepare-fixture.py"))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    info = json.loads((fixture / "fixture.json").read_text())
    for name in ("rootfs.erofs", "production-ablx-shim.bin", "root-labels.json", "kernel-bundle/bundle.json"):
        helper.require_regular(helper.safe_child(fixture, name))
    helper.verify_reuse(fixture, info.get("input_fingerprint"))
    labels = json.loads((fixture / "root-labels.json").read_text())
    if labels.get("result") != "pass" or labels.get("rootfs_sha256") != info["artifacts"]["rootfs.erofs"]["sha256"]:
        raise ValueError("fixture lacks a passing label proof for its exact rootfs")
    return info


def prepare(args):
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    started = time.time()
    state = {"schema_version": 1, "phase": "preparing", "started_at": started}
    write_json(run / "status.json", state)
    try:
        fixture = args.fixture.resolve(strict=True)
        recipe = json.loads(args.profile.read_text())
        fixture_manifest = fixture / "fixture.json"
        fixture_info = verify_fixture(fixture)
        if fixture_info["inputs"]["dtb"] != recipe["devicetree_name"] + ".dtb":
            raise ValueError("fixture device tree does not match selected profile")
        serial = safe_name(args.device_serial)
        recipe_id = recipe["id"]
        repo = Path(__file__).resolve().parents[2]
        modules = early_modules(recipe, repo)
        root_mode = getattr(args, "root_mode", "usb")
        if root_mode == "ram":
            modules.append("loop")
        bundle = (args.kernel_bundle.resolve(strict=True) if args.kernel_bundle is not None
                  else fixture / "kernel-bundle/bundle.json")
        kernel = json.loads(bundle.read_text())
        expected_dtb = Path(recipe["devicetree_name"]).name + ".dtb"
        if Path(kernel["dtb"]["path"]).name != expected_dtb:
            raise ValueError("kernel bundle device tree does not match selected profile: " + expected_dtb)
        verify_required_modules(bundle, modules)
        config = bundle.parent / "kernel.config"
        if config.is_symlink() or (config.exists() and not config.is_file()):
            raise ValueError("kernel bundle config must be a regular file when present")
        kernel_config = {"status": "absent", "path": None, "sha256": None}
        if config.is_file():
            kernel_config = {"status": "present", "path": str(config), "sha256": sha256(config)}
        devpro = {key: recipe[key] for key in
                  ["id", "display_name", "devicetree_name", "match", "probe", "boot"]}
        devpro["id"] = f"pocketfed-{recipe_id}-{serial}"
        devpro["probe"] = [*devpro["probe"], {"fastboot.getvar": "serialno", "equals": serial}]
        schemas = run / "devpro"
        schemas.mkdir()
        write_json(schemas / (devpro["id"] + ".json"), devpro)
        devpro_path = schemas / (devpro["id"] + ".json")
        tool_dir = run / "tools"
        tool_dir.mkdir()
        source_tools = {}
        for name, source in (("kboop", args.kboop), ("kboop-init", args.init)):
            source = source.resolve(strict=True)
            digest = sha256(source)
            copied = tool_dir / name
            shutil.copy2(source, copied)
            if sha256(copied) != digest:
                raise ValueError("tool changed while snapshotting: " + str(source))
            source_tools[name] = {"path": str(source), "sha256": digest}
        argv = [str(tool_dir / "kboop"), "--rootfs", str(fixture / "rootfs.erofs"),
                "--kernel-bundle", str(bundle), "--work-dir", str(run / "artifacts"),
                "--init", str(tool_dir / "kboop-init"), "--device-profile", devpro["id"],
                "--usb-serial", f"pf-{serial}", "--no-serial", "--wait", "120"]
        if "ramdisk_offset" in recipe:
            # Pixel ABL policy: rebuild the payload around the production ABLX
            # shim and pin the ramdisk address ABL loads. Loaders that parse
            # the boot sections themselves (Pocketboot kexec) need neither, so
            # a profile without a ramdisk offset boots without them.
            argv += ["--abl-exorcist", str(fixture / "production-ablx-shim.bin"),
                     "--abl-exorcist-mode", "ramdisk",
                     "--ramdisk-offset", hex(recipe["ramdisk_offset"])]
        if root_mode == "ram":
            argv.append("--resident-root")
        for module in modules:
            argv += ["--early-module", module]
        argv += ["--cmdline", " ".join([*recipe["cmdline"], f"pocketfed.liveboot={safe_name(run.name)}", f"pocketfed.root_mode={root_mode}"])]
        manifest = {
            "schema_version": 1, "run_id": run.name, "device_serial": serial,
            "profile": recipe, "root_mode": root_mode, "kernel_release": kernel["release"],
            "kernel_bundle": {"path": str(bundle), "sha256": sha256(bundle),
                              "source": "override" if args.kernel_bundle is not None else "fixture"},
            "kernel_config": kernel_config,
            "inputs": {str(path): sha256(path) for path in
                       [fixture_manifest, bundle, fixture / "rootfs.erofs", fixture / "production-ablx-shim.bin",
                        tool_dir / "kboop", tool_dir / "kboop-init"]},
            "source_tools": source_tools,
            "fixture": str(fixture), "fixture_image": fixture_info["inputs"]["image"], "argv": argv,
            "environment": {"FASTBOOP_SCHEMA_PATH": str(schemas),
                            "RUST_LOG": os.environ.get("RUST_LOG", "info")},
        }
        provenance_files = {}
        for name in ("provenance.json", "source.patch", "build.log", "System.map"):
            path = bundle.parent / name
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError("kernel provenance must be a regular file: " + str(path))
            if path.is_file():
                digest = sha256(path)
                provenance_files[name] = {"path": str(path), "sha256": digest}
                manifest["inputs"][str(path)] = digest
        manifest["kernel_provenance"] = provenance_files
        if kernel_config["status"] == "present":
            manifest["inputs"][str(config)] = kernel_config["sha256"]
        write_json(run / "run.json", manifest)
        environment = os.environ | manifest["environment"]
        with (run / "prepare.log").open("wb") as log:
            subprocess.run([*argv, "--no-boot"], env=environment, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        manifest["boot_image_sha256"] = sha256(run / "artifacts/boot.img")
        prepared = {"schema_version": 1}
        for key, path in [("rootfs", fixture / "rootfs.erofs"),
                          ("modules_image", run / "artifacts/modules.ero"),
                          ("boot_image", run / "artifacts/boot.img")]:
            prepared[key] = {"path": str(path), "sha256": sha256(path)}
        write_json(run / "prepared.json", prepared)
        manifest["inputs"][str(devpro_path)] = sha256(devpro_path)
        manifest["inputs"][str(run / "prepared.json")] = sha256(run / "prepared.json")
        manifest["boot_argv"] = [argv[0], "--prepared", str(run / "prepared.json"),
                                 "--device-profile", devpro["id"], "--usb-serial", f"pf-{serial}",
                                 "--no-serial", "--wait", "120"]
        finished = time.time()
        manifest["preparation"] = {"started_at": started, "finished_at": finished,
                                   "duration_seconds": finished - started}
        write_json(run / "run.json", manifest)
        state.update(phase="prepared", duration_seconds=finished - started)
        print(json.dumps({"phase": "prepared", "run_dir": str(run)}), flush=True)
    except Exception as error:
        state.update(phase="failed", error=str(error))
        raise
    finally:
        write_json(run / "status.json", state)


@contextlib.contextmanager
def uart_control_deadline():
    """Bound terminal ioctls as well as nonblocking writes in the main loop."""
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(signum, frame):
        raise TimeoutError("UART SysRq transaction exceeded two seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            remaining = max(0.001, old_timer[0] - (time.monotonic() - started))
            signal.setitimer(signal.ITIMER_REAL, remaining, old_timer[1])


def uart_sysrq(uart, key):
    """Use the FTDI low-baud BREAK approximation, restoring normal baud on error."""
    payload = {"help": b"h", "reboot": b"b"}.get(key)
    if payload is None:
        raise ValueError("SysRq key must be help or reboot")
    attrs = termios.tcgetattr(uart)
    normal = list(attrs)
    normal[4] = normal[5] = termios.B115200
    slow = list(attrs)
    slow[4] = slow[5] = termios.B300
    with uart_control_deadline():
        try:
            termios.tcsetattr(uart, termios.TCSANOW, slow)
            if os.write(uart, b"\0") != 1:
                raise OSError("short UART BREAK write")
            termios.tcdrain(uart)
            time.sleep(0.1)
        finally:
            termios.tcsetattr(uart, termios.TCSANOW, normal)
        time.sleep(0.2)
        if os.write(uart, payload) != 1:
            raise OSError("short UART SysRq key write")
        termios.tcdrain(uart)


def control_lines(pending, data):
    """Recognize only complete allowlisted lines, with bounded partial storage."""
    lines = (pending + data).split(b"\n")
    pending = lines.pop()
    if len(pending) > 64:
        # Poison an oversized partial line until its newline, never reinterpret
        # its truncated tail as a valid command.
        pending = b"\0"
    return [line.decode("ascii") for line in lines if line in (b"help", b"reboot")], pending


def can_release_usb_host(result):
    resident = result.get("resident", {})
    return (result.get("root_mode") == "ram" and result.get("result") == "pass"
            and isinstance(resident, dict) and resident.get("smoo_detached") is True
            and resident.get("hashes_verified") is True
            and result.get("checks", {}).get("root_transport_ready") is True)


def sysrq(args):
    """Queue one operator command to an already-running host without opening UART."""
    run = args.run_dir.resolve(strict=True)
    manifest = json.loads((run / "run.json").read_text())
    state = json.loads((run / "status.json").read_text())
    if (state.get("phase") not in ("booting", "hosting", "console") or
        state.get("run_id") != manifest["run_id"] or manifest["run_id"] != run.name):
        raise ValueError("no active host for this exact run")
    if not state.get("control_ready"):
        raise ValueError("SysRq is disarmed until UART shows this run's exact pocketfed.liveboot token")
    if args.key not in ("help", "reboot"):
        raise ValueError("SysRq key must be help or reboot")
    path = run / "control"
    try:
        info = path.lstat()
        if (not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid() or
            stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("unsafe run control FIFO")
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENXIO):
            raise ValueError("no active host is reading this run's control FIFO") from error
        raise
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("run control FIFO changed while opening")
        payload = (args.key + "\n").encode("ascii")
        try:
            written = os.write(fd, payload)
        except (BlockingIOError, BrokenPipeError) as error:
            raise ValueError("control FIFO is busy or its host stopped; command was not queued") from error
        if written != len(payload):
            raise ValueError("short control FIFO write; command was not queued completely")
    finally:
        os.close(fd)
    print(json.dumps({"run_id": manifest["run_id"], "sysrq": args.key, "status": "queued"}), flush=True)


def boot(args):
    run = args.run_dir.resolve(strict=True)
    manifest = json.loads((run / "run.json").read_text())
    for path, expected in manifest["inputs"].items():
        if sha256(path) != expected:
            raise ValueError(f"prepared input changed: {path}")
    locks = Path(tempfile.gettempdir()) / f"pocketfed-liveboot-locks-{os.getuid()}"
    if locks.exists() and (locks.is_symlink() or locks.stat().st_uid != os.getuid()):
        raise ValueError("unsafe shared device-lock directory")
    locks.mkdir(exist_ok=True, mode=0o700)
    with (locks / "smoo-host.lock").open("a") as host_lock, \
            (locks / (safe_name(manifest["device_serial"]) + ".lock")).open("a") as lock:
        try:
            fcntl.flock(host_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another liveboot runner owns smoo hosting; only one USB-root session is supported") from error
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        uart = None
        original_termios = None
        child = None
        control = None
        control_identity = None
        control_path = run / "control"
        state = {"schema_version": 1, "phase": "booting", "started_at": time.time(),
                 "uart": str(args.uart), "run_id": manifest["run_id"], "control_ready": False}
        try:
            holders = subprocess.run(["fuser", str(args.uart)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, check=False)
            if holders.returncode == 0:
                raise ValueError(f"UART is already open by process(es): {holders.stdout.decode().strip()}")
            if holders.returncode != 1:
                raise ValueError("could not establish UART ownership: " + holders.stderr.decode().strip())
            uart = os.open(args.uart, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            original_termios = termios.tcgetattr(uart)
            fcntl.ioctl(uart, termios.TIOCEXCL)
            attrs = termios.tcgetattr(uart)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(uart, termios.TCSANOW, attrs)
            termios.tcflush(uart, termios.TCIFLUSH)
            os.mkfifo(control_path, 0o600)
            info = control_path.lstat()
            control_identity = (info.st_dev, info.st_ino)
            control = os.open(control_path, os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW)
            os.fchmod(control, 0o600)
            with (run / "host.log").open("wb") as host_log, (run / "uart.log").open("ab", buffering=0) as uart_log:
                child = subprocess.Popen(manifest["boot_argv"], env=os.environ | manifest["environment"],
                                         stdout=host_log, stderr=subprocess.STDOUT, start_new_session=True)
                state["host_pid"] = child.pid
                write_json(run / "status.json", state)
                pending = b""
                control_pending = b""
                run_token = ("pocketfed.liveboot=" + safe_name(manifest["run_id"])).encode("ascii")
                keep_console = False
                while child.poll() is None or keep_console:
                    ready, _, _ = select.select([uart, control], [], [], 0.1)
                    data = b""
                    if uart in ready:
                        try:
                            data = os.read(uart, 65536)
                        except BlockingIOError:
                            pass
                    if data:
                        uart_log.write(data)
                        pending += data
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            has_run_token = run_token in line.split()
                            if (b"Linux version " in line or b"QC_IMAGE_VERSION_STRING=BOOT." in line or
                                b"Enter reason of bootloader mode:" in line or
                                (b"Kernel command line:" in line and not has_run_token)):
                                state.update(control_ready=False, control_disabled_reason="new or unmatched kernel boot")
                                write_json(run / "status.json", state)
                            elif not state["control_ready"] and has_run_token:
                                state.update(control_ready=True, control_enabled_at=time.time())
                                state.pop("control_disabled_reason", None)
                                write_json(run / "status.json", state)
                            marker = b"POCKETFED_LIVEBOOT_RESULT="
                            if marker in line:
                                try:
                                    result = json.loads(line.split(marker, 1)[1].decode().strip())
                                except (ValueError, UnicodeDecodeError):
                                    continue
                                if (not isinstance(result, dict) or
                                    result.get("run_id") != manifest["run_id"] or
                                    result.get("kernel_release") != manifest["kernel_release"] or
                                    result.get("root_mode", "usb") != manifest.get("root_mode", "usb") or
                                    result.get("result") not in ("pass", "fail")):
                                    continue
                                write_json(run / "result.json", result)
                                state.update(phase="hosting", result=result["result"],
                                             handoff_seconds=time.time() - state["started_at"])
                                if can_release_usb_host(result) and not keep_console:
                                    # The device verified its RAM copies, mounted loops and
                                    # detached smoo. Keep independent UART recovery alive.
                                    keep_console = True
                                    with contextlib.suppress(ProcessLookupError):
                                        os.killpg(child.pid, signal.SIGTERM)
                                    try:
                                        child.wait(timeout=3)
                                    except subprocess.TimeoutExpired:
                                        with contextlib.suppress(ProcessLookupError):
                                            os.killpg(child.pid, signal.SIGKILL)
                                        child.wait(timeout=3)
                                    fcntl.flock(host_lock, fcntl.LOCK_UN)
                                    state.update(phase="console", usb_host_released=True, host_lock_released=True,
                                                 host_exit_code=child.returncode)
                                write_json(run / "status.json", state)
                                print(json.dumps({"phase": state["phase"], "result": result["result"],
                                                  "run_dir": str(run)}), flush=True)
                        pending = pending[-65536:]
                    if control in ready:
                        try:
                            commands, control_pending = control_lines(control_pending, os.read(control, 4096))
                        except BlockingIOError:
                            commands = []
                        for key in commands:
                            record = {"time": time.time(), "run_id": manifest["run_id"], "key": key,
                                      "status": "accepted" if state["control_ready"] else "rejected-unverified-run"}
                            with (run / "control.log").open("a") as log:
                                log.write(json.dumps(record) + "\n")
                            if not state["control_ready"]:
                                continue
                            try:
                                uart_sysrq(uart, key)
                            except (OSError, termios.error) as error:
                                record.update(time=time.time(), status="failed", error=str(error))
                            else:
                                record.update(time=time.time(), status="sent")
                            if key == "reboot":
                                # A reset can leave this phone in a different boot;
                                # require fresh matching evidence before another command.
                                state.update(control_ready=False, control_disabled_reason="reboot requested")
                                write_json(run / "status.json", state)
                            with (run / "control.log").open("a") as log:
                                log.write(json.dumps(record) + "\n")
                    if state["phase"] == "booting" and time.time() - state["started_at"] > args.timeout:
                        state.update(phase="hosting", result="handoff-timeout")
                        write_json(run / "status.json", state)
                        print(json.dumps(state), flush=True)
                state.update(phase="stopped", exit_code=child.returncode)
        except (KeyboardInterrupt, SystemExit):
            state.update(phase="stopped", reason="operator stopped host; USB root no longer served")
        except Exception as error:
            state.update(phase="failed", error=str(error))
            raise
        finally:
            try:
                if child is not None and child.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
            finally:
                if control is not None:
                    with contextlib.suppress(OSError):
                        os.close(control)
                if control_identity is not None:
                    with contextlib.suppress(OSError):
                        info = control_path.lstat()
                        if (info.st_dev, info.st_ino) == control_identity:
                            control_path.unlink()
                if uart is not None:
                    if original_termios is not None:
                        with contextlib.suppress(OSError, termios.error):
                            termios.tcsetattr(uart, termios.TCSANOW, original_termios)
                    with contextlib.suppress(OSError):
                        fcntl.ioctl(uart, termios.TIOCNXCL)
                    with contextlib.suppress(OSError):
                        os.close(uart)
                write_json(run / "status.json", state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare", help="host-only artifact assembly; no device access")
    prep.add_argument("--profile", type=Path, required=True)
    prep.add_argument("--fixture", type=Path, required=True)
    prep.add_argument("--root-mode", choices=("usb", "ram"), default="usb",
                      help="usb streams storage; ram copies/verifies EROFS before detaching USB")
    prep.add_argument("--kernel-bundle", type=Path,
                      help="candidate bundle.json; defaults to the fixture's baseline kernel bundle")
    prep.add_argument("--kboop", type=Path, default=Path(__file__).resolve().parents[3] / "kboop/target/release/kboop")
    prep.add_argument("--init", type=Path, default=Path(__file__).resolve().parents[3] / "kboop/target/aarch64-unknown-linux-musl/release/kboop-init")
    prep.add_argument("--device-serial", required=True)
    prep.add_argument("--run-dir", type=Path, required=True)
    host = sub.add_parser("boot", help="RAM boot and keep serving rootfs; never flashes or changes slots")
    host.add_argument("--run-dir", type=Path, required=True)
    host.add_argument("--uart", type=Path, required=True)
    host.add_argument("--timeout", type=int, default=300,
                      help="report handoff timeout but keep root storage alive")
    recovery = sub.add_parser("sysrq", help="request one gated UART SysRq command from an active host")
    recovery.add_argument("--run-dir", type=Path, required=True)
    recovery.add_argument("--key", choices=("help", "reboot"), required=True)
    args = parser.parse_args()
    if args.action == "boot":
        def terminate(signum, frame):
            raise SystemExit(128 + signum)
        for signum in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(signum, terminate)
    {"prepare": prepare, "boot": boot, "sysrq": sysrq}[args.action](args)


if __name__ == "__main__":
    main()
