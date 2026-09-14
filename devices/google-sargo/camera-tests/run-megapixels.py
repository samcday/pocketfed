#!/usr/bin/env python3
"""Exercise the installed app and real cameras in a private 360x720 Phoc session.

Run as the desktop user. Photos/screenshots are private trial output and must not
be committed. This checks rendering, capture and reopen, not physical image quality.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True)
parser.add_argument("--cycles", type=int, default=2)
parser.add_argument("--shots", type=int, default=2)
parser.add_argument("--capture-timeout", type=int, default=120)
parser.add_argument("--pointer-tool", type=Path, help="native virtual-pointer helper, used only on this private Wayland socket")
parser.add_argument("--preview-seconds", type=int, default=5)
parser.add_argument("--trace-ioctl", action="store_true", help="record a private strace log for each app launch")
parser.add_argument("--private-child", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
if not (1 <= args.cycles <= 10 and 1 <= args.shots <= 10 and 1 <= args.capture_timeout <= 600):
    parser.error("cycles/shots must be 1..10 and capture-timeout must be 1..600 seconds")
if not 1 <= args.preview_seconds <= 120:
    parser.error("preview-seconds must be 1..120")
if args.pointer_tool and not os.access(args.pointer_tool, os.X_OK):
    parser.error("pointer-tool must be an executable file")
commands = ["dbus-run-session", "gdbus", "grim", "phoc", "megapixels",
            "megapixels-findconfig", "rpm", "exiftool", "magick", "stdbuf"]
if args.trace_ioctl:
    commands.append("strace")
missing = [name for name in commands if shutil.which(name) is None]
if missing:
    parser.error("Missing test tools: " + ", ".join(missing))
output = Path(args.output).resolve()
if not args.private_child:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    bus_config = output / "bus.conf"
    bus_config.write_text('''<busconfig><type>session</type><keep_umask/>
<listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>
<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/>
</policy></busconfig>''')
    with (output / "bus.log").open("w") as log:
        result = subprocess.run(["dbus-run-session", "--config-file=" + str(bus_config),
                                 "--", sys.executable, str(Path(__file__).resolve()),
                                 *sys.argv[1:], "--private-child"], stderr=log)
    raise SystemExit(result.returncode)

os.umask(0o077)
runtime, config, pictures = (output / n for n in ("runtime", "config", "pictures"))
for directory in (runtime, config, pictures):
    directory.mkdir(mode=0o700)
(config / "user-dirs.dirs").write_text(f'XDG_PICTURES_DIR="{pictures}"\n')
phoc_config = output / "phoc.ini"
phoc_config.write_text("[output:HEADLESS-1]\nmode=360x720\nscale=1\n")
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="camera-test",
           XDG_CONFIG_HOME=str(config), XDG_DATA_HOME=str(output / "data"),
           XDG_CACHE_HOME=str(output / "cache"), XDG_PICTURES_DIR=str(pictures),
           WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1", WLR_RENDERER="gles2",
           GDK_BACKEND="wayland", GSK_RENDERER="gl", GTK_A11Y="none",
           GSETTINGS_BACKEND="memory", GTK_USE_PORTAL="0")
for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "DISPLAY"):
    env.pop(key, None)
processes = []
results = {"kernel": os.uname().release, "status": "failed", "captures": [],
           "requested_cycles": args.cycles, "requested_shots_per_cycle": args.shots,
           "capture_timeout": args.capture_timeout, "preview_seconds": args.preview_seconds,
           "private_pointer_used": bool(args.pointer_tool)}


def start(argv, log_name):
    with (output / log_name).open("w") as log:
        process = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    processes.append(process)
    return process


def run(argv, timeout=10, **kwargs):
    return subprocess.run(argv, env=env, capture_output=True, text=True,
                          check=True, timeout=timeout, **kwargs).stdout


def wait_for(check, label, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if check():
            return
        if any(p.poll() is not None for p in processes):
            raise RuntimeError("Process exited while waiting for " + label)
        time.sleep(.1)
    raise RuntimeError("Timed out waiting for " + label)


def action(name):
    return run(["gdbus", "call", "--session", "--dest", "me.gapixels.Megapixels",
                "--object-path", "/me/gapixels/Megapixels", "--method",
                "org.gtk.Actions.Activate", name, "[]", "{}"])


try:
    results["packages"] = run(["rpm", "-q", "megapixels", "libmegapixels", "libdng", "phoc"])
    discovery = run(["megapixels-findconfig"])
    results["discovery"] = discovery
    rear = re.search(r"^----\[ Camera Rear \((\d+)\) \]----$", discovery, re.MULTILINE)
    if rear is None:
        raise RuntimeError("No unambiguous Rear camera in installed configuration")
    rear_index = int(rear.group(1))
    compositor = start(["phoc", "--no-xwayland", "--socket=camera-test", "-C", str(phoc_config)], "phoc.log")
    wait_for(lambda: (runtime / "camera-test").exists(), "compositor socket")
    for cycle in range(args.cycles):
        app_command = ["stdbuf", "-oL", "-eL", "megapixels"]
        if args.trace_ioctl:
            app_command = ["strace", "--kill-on-exit", "-f", "-tt", "-yy",
                           "-e", "trace=ioctl,poll,ppoll", "-o",
                           str(output / f"ioctl-{cycle}.log"), "--", *app_command]
        app = start(app_command, f"app-{cycle}.log")
        run(["gdbus", "wait", "--session", "--timeout", "15", "me.gapixels.Megapixels"])
        time.sleep(3)
        if args.pointer_tool:
            # Empty space in the observed top toolbar: activate without toggling
            # exposure, focus, flash, or capture. env always points to private Phoc.
            run([str(args.pointer_tool.resolve()), "360", "720", "240", "24"])
        # Resolve order from the installed configuration, including rear-first builds.
        for _ in range(rear_index):
            action("switch-camera")
        time.sleep(args.preview_seconds)
        run(["grim", str(output / f"rear-preview-{cycle}.png")])
        for shot in range(args.shots):
            before = set(pictures.glob("*.jpg"))
            action("capture")
            wait_for(lambda: bool(set(pictures.glob("*.jpg")) - before), "JPEG creation", args.capture_timeout)
            jpeg = sorted(set(pictures.glob("*.jpg")) - before)[0]
            # ExifTool adds this tag at the end of the installed postprocessor.
            def metadata_finished():
                try:
                    return run(["exiftool", "-s3", "-Software", str(jpeg)]).strip() == "Megapixels"
                except subprocess.CalledProcessError:
                    # The file may still be incomplete or undergoing its final rename.
                    return False

            wait_for(metadata_finished, "postprocessor metadata", args.capture_timeout)
            # Allow its final rename and the application's completion callback.
            stability = {"stat": None, "since": time.monotonic()}

            def jpeg_stable():
                try:
                    info = jpeg.stat()
                except FileNotFoundError:
                    stability["since"] = time.monotonic()
                    return False
                new_stat = (info.st_size, info.st_mtime_ns)
                if new_stat != stability["stat"]:
                    stability.update(stat=new_stat, since=time.monotonic())
                return time.monotonic() - stability["since"] >= 3

            wait_for(jpeg_stable, "stable completed JPEG", 30)
            # Read the pixels too: intact EXIF does not prove an intact JPEG.
            run(["magick", "-regard-warnings", str(jpeg), "null:"], timeout=30)
            metadata = json.loads(run(["exiftool", "-j", "-ImageWidth", "-ImageHeight", "-Orientation",
                                      "-Make", "-Model", "-Software", str(jpeg)]))[0]
            if metadata.get("ImageWidth", 0) * metadata.get("ImageHeight", 0) != 4032 * 3024:
                raise RuntimeError("JPEG dimensions do not match the selected rear mode")
            metadata.update(cycle=cycle, shot=shot)
            results["captures"].append(metadata)
            run(["grim", str(output / f"rear-after-capture-{cycle}-{shot}.png")])
        action("quit")
        app.wait(timeout=10)
        processes.remove(app)
        if app.returncode != 0:
            raise RuntimeError(f"App exited {app.returncode}")
        time.sleep(2)
    results["status"] = "passed"
except Exception as error:
    results["error"] = str(error)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    (output / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
raise SystemExit(0 if results["status"] == "passed" else 1)
