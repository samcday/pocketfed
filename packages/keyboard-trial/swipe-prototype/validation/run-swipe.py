#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise swipe capture, visible decay and explicit commit in private Phoc/GTK4.

The pointer clicks the real keyboard. This does not emulate an input method or
write text into the application. Run the helper build commands in README first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--stevia", default="/usr/bin/phosh-osk-stevia",
                    help="Stevia executable (can be extracted from a trial RPM)")
parser.add_argument("--case", choices=["swipe", "swipe-focus", "literal", "phrase", "completion", "correction", "helo", "helo-literal", "focus", "backspace", "unavailable"], default="literal")
parser.add_argument("--service-command", default='["/usr/bin/verbisaged", "--mode", "dbus"]')
parser.add_argument("--dictionary", default="/usr/share/android-patricia-dictionaries/en_US.dict",
                    help="Dictionary used by the service; recorded for provenance")
parser.add_argument("--container-rendering", action="store_true",
                    help="Allow Glycin rendering without nested bwrap inside the test container")
parser.add_argument("--tools-dir", required=True, help="Directory with virtual-pointer, virtual-drag and gtk4-probe.py")
parser.add_argument("--schema-dir", required=True, help="Private compiled schemas with swipe-typing enabled")
parser.add_argument("--defer-pixel-check", action="store_true",
                    help="Capture trail frames without Pillow; verify-trail.py must validate them on a host")
parser.add_argument("--private-bus-child", action="store_true", help=argparse.SUPPRESS)
args = parser.parse_args()
if not args.private_bus_child:
    child = subprocess.run(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                            *sys.argv[1:], "--private-bus-child"], capture_output=True, text=True)
    if Path(args.output).exists():
        (Path(args.output) / "dbus.log").write_text(child.stderr)
    print(child.stdout, end="")
    raise SystemExit(child.returncode)

base = Path(args.tools_dir).resolve()
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=False)
runtime = output / "runtime"
runtime.mkdir(mode=0o700)
config = output / "phoc.ini"
config.write_text("[output:HEADLESS-1]\nmode=360x720\nscale=1\n")
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="stevia-test",
           XDG_CONFIG_HOME=str(output / "config"), XDG_DATA_HOME=str(output / "data"),
           WLR_BACKENDS="headless", WLR_HEADLESS_OUTPUTS="1", WLR_RENDERER="pixman",
           GDK_BACKEND="wayland", GTK_IM_MODULE="wayland", GSK_RENDERER="cairo",
           GTK_A11Y="none", GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1",
           GTK_USE_PORTAL="0", GSETTINGS_SCHEMA_DIR=str(Path(args.schema_dir).resolve()),
           POS_TEST_LAYOUT="us", POS_TEST_COMPLETER="verbisage", POS_DEBUG="force-show")
env.pop("LD_LIBRARY_PATH", None)
env.pop("LD_PRELOAD", None)
env.pop("GLYCIN_DISABLE_SANDBOX", None)
if args.container_rendering:
    env["GLYCIN_DISABLE_SANDBOX"] = "i-know-the-risks"
processes = []
result = {"case": args.case, "status": "invalid",
          "test_environment": {"GLYCIN_DISABLE_SANDBOX": env.get("GLYCIN_DISABLE_SANDBOX", "unset")}}


def start(argv, name, child_env=env):
    with (output / name).open("w") as stream:
        proc = subprocess.Popen(argv, env=child_env, stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=True)
    processes.append(proc)
    return proc


def events():
    values = []
    for line in (output / "probe.log").read_text().splitlines():
        if line.startswith('{"event":'):
            values.append(json.loads(line))
    return values


def wait_for(check, label, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        for proc in processes:
            if proc.poll() is not None:
                raise RuntimeError(f"Process {proc.args[0]} exited {proc.returncode} waiting for {label}")
        time.sleep(.025)
    raise RuntimeError(f"Timed out waiting for {label}")


def observed(event, text):
    return any(e["event"] == event and e["text"] == text for e in events())


def click(x, y):
    subprocess.run([str(base / "virtual-pointer"), "360", "720", str(x), str(y)],
                   env=env, check=True, timeout=3)
    time.sleep(.08)


def key(char):
    # The pinned us layout has ten equal columns and four 50px rows.
    rows = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
    for row, letters in enumerate(rows):
        if char in letters:
            offset = (0, .5, 1.5)[row]
            click(round((letters.index(char) + offset + .5) * 36), 545 + row * 50)
            return
    if char == " ":
        click(180, 695)
    elif char == "BACKSPACE":
        click(338, 645)
    else:
        raise ValueError(char)


def screenshot(name):
    subprocess.run(["grim", str(output / name)], env=env, check=False, timeout=3,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


try:
    result["installed_package_context"] = subprocess.run(
        ["rpm", "-q", "stevia", "gtk4", "phoc", "verbisage", "android-patricia-dictionaries-en-US"],
        capture_output=True, text=True).stdout.splitlines()
    result["stevia_executable"] = str(Path(args.stevia).resolve())
    result["stevia_sha256"] = hashlib.sha256(Path(args.stevia).read_bytes()).hexdigest()
    result["stevia_source"] = "installed" if args.stevia == "/usr/bin/phosh-osk-stevia" else "executable override; installed RPM listing is environment context only"
    result["service_command"] = json.loads(args.service_command)
    result["service_sha256"] = hashlib.sha256(Path(result["service_command"][0]).read_bytes()).hexdigest()
    dictionary = Path(args.dictionary).resolve()
    if args.case == "unavailable":
        dictionary = output / "deliberately-missing.dict"
        missing_config = output / "missing-dictionary.toml"
        missing_config.write_text('backend="patricia"\nlanguage_default="en_US"\n'
                                  '[backends.patricia]\ntype="patricia"\npath=' + json.dumps(str(dictionary)) + '\n')
        service_args = result["service_command"]
        if "--config" in service_args:
            index = service_args.index("--config")
            del service_args[index:index + 2]
        service_args.extend(["--config", str(missing_config)])
    result["dictionary"] = str(dictionary)
    result["dictionary_exists"] = dictionary.exists()
    result["dictionary_sha256"] = hashlib.sha256(dictionary.read_bytes()).hexdigest() if dictionary.exists() else None
    start(["phoc", "--no-xwayland", "--socket=stevia-test", "-C", str(config)], "phoc.log")
    wait_for(lambda: (runtime / "stevia-test").exists(), "headless output")
    start(result["service_command"], "verbisage.log")
    subprocess.run(["gdbus", "wait", "--session", "--timeout", "5", "org.verbisage.Dictionary"],
                   env=env, check=True, timeout=6)
    if args.case == "unavailable":
        check = subprocess.run(["gdbus", "call", "--session", "--dest", "org.verbisage.Dictionary",
                                "--object-path", "/org/verbisage/Dictionary", "--method",
                                "org.verbisage.Dictionary1.Complete", "teh", "6", "en_US"],
                               env=env, capture_output=True, text=True, timeout=3)
        result["dictionary_error_check"] = {"returncode": check.returncode, "stderr": check.stderr.strip()}
        assert check.returncode != 0 and "org.freedesktop.DBus.Error.Failed" in check.stderr, "Missing dictionary must return a service error"
    osk_env = dict(env, G_MESSAGES_DEBUG="all", WAYLAND_DEBUG="client")
    start([args.stevia], "stevia.log", osk_env)
    probe = start([sys.executable, str(base / "gtk4-probe.py")], "probe.log")
    wait_for(lambda: observed("ready", ""), "GTK field")
    # Headless Phoc may not schedule frames while the initially hidden OSK is
    # offscreen. Stevia finishes that initial animation after its 1.5s guard.
    time.sleep(2)
    screenshot("initial.png")
    if args.case.startswith("swipe"):
        # Pinned 360px US layout. Interpolate real pointer movements across h-e-l-o.
        controls = [(216, 595), (90, 545), (324, 595), (306, 545)]
        points = [(*controls[0], 0)]
        elapsed = 0
        for first, last in zip(controls, controls[1:]):
            for step in range(1, 13):
                elapsed += 20
                points.append((round(first[0] + (last[0] - first[0]) * step / 12),
                               round(first[1] + (last[1] - first[1]) * step / 12), elapsed))
        trace = output / "trace.txt"
        trace.write_text("".join(f"{x} {y} {t}\n" for x, y, t in points))
        drag = subprocess.Popen([str(base / "virtual-drag"), "360", "720", str(trace)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        processes.append(drag)
        for line in drag.stdout:
            if line.strip() == "POINT 20":
                screenshot("trail-moving.png")
                if args.case == "swipe-focus":
                    os.kill(probe.pid, signal.SIGUSR1)
                    wait_for(lambda: observed("focus", "button"), "focus change during swipe")
        assert drag.wait(timeout=3) == 0, drag.stderr.read()
        processes.remove(drag)
        # A swipe must never leak crossed-key letters into the app.
        assert not any(e["event"] in ("buffer", "preedit") and e["text"] for e in events()), "Swipe leaked text or preedit"
        time.sleep(.08)
        screenshot("trail-released.png")
        time.sleep(.55)
        screenshot("trail-decaying.png")
        time.sleep(1.4)
        screenshot("trail-cleared.png")
        time.sleep(.2)
        screenshot("trail-reference.png")
        assert not any(e["event"] in ("buffer", "preedit") and e["text"] for e in events()), "Unselected swipe candidate entered text or preedit"
        if args.case == "swipe":
            if args.defer_pixel_check:
                result["trail_pixel_check"] = "deferred; run verify-trail.py on the captured frames"
            else:
                from PIL import Image, ImageChops, ImageStat
                reference = Image.open(output / "trail-reference.png").convert("RGB").crop((0, 520, 360, 720))
                energy = {}
                for name in ["released", "decaying", "cleared"]:
                    frame = Image.open(output / f"trail-{name}.png").convert("RGB").crop((0, 520, 360, 720))
                    energy[name] = sum(ImageStat.Stat(ImageChops.difference(reference, frame)).sum)
                result["trail_difference_energy"] = energy
                assert energy["released"] > energy["decaying"] > energy["cleared"], "Trail must visibly decay then disappear"
                assert energy["cleared"] == 0, "Trail animation should finish"
            # Swipe has no literal entry: first result is the first actual candidate.
            click(42, 493)
            wait_for(lambda: observed("buffer", "hello "), "selected swipe candidate commit")
            commits = [e["text"] for e in events() if e["event"] == "buffer" and e["text"]]
            assert commits[-1] == "hello " and all(t in ("hello", "hello ") for t in commits), commits
        else:
            assert observed("focus", "button")
        screenshot("final.png")
        result["events"] = events()
        result["status"] = "pending-pixel-check" if args.case == "swipe" and args.defer_pixel_check else "passed"
    else:
        word = {"literal": "hello", "phrase": "hello", "unavailable": "hello", "completion": "hell", "correction": "teh", "helo": "helo", "helo-literal": "helo",
                "focus": "hell", "backspace": "hello"}[args.case]
        for index, char in enumerate(word):
            key(char)
            wait_for(lambda i=index: observed("preedit", word[:i + 1]), f"preedit {word[:index + 1]}")
        time.sleep(.5)
        screenshot("candidates.png")
        if args.case == "focus":
            os.kill(probe.pid, signal.SIGUSR1)
            wait_for(lambda: observed("focus", "button"), "focus change")
            wait_for(lambda: observed("preedit", ""), "preedit reset")
            time.sleep(.25)
            assert not any(e["event"] == "buffer" and e["text"] for e in events()), "Unexpected commit after focus loss"
        elif args.case in ("completion", "correction", "helo"):
            # The first candidate is the raw word, the next is the requested result.
            click(125, 493)
            expected = "the " if args.case == "correction" else "hello "
            wait_for(lambda: observed("buffer", expected), "selected candidate commit")
        else:
            if args.case == "backspace":
                key("BACKSPACE")
                wait_for(lambda: observed("preedit", "hell"), "backspace preedit")
                word = "hell"
            key(" ")
            wait_for(lambda: observed("buffer", word + " "), "literal commit")
            if args.case == "phrase":
                for index, char in enumerate("world"):
                    key(char)
                    wait_for(lambda i=index: observed("preedit", "world"[:i + 1]), "next word preedit")
                key(" ")
                wait_for(lambda: observed("buffer", "hello world "), "second word commit")
        screenshot("final.png")
        result["events"] = events()
        result["status"] = "passed"
except Exception as error:
    result["error"] = str(error)
    if (runtime / "stevia-test").exists():
        screenshot("failure.png")
    if (output / "probe.log").exists():
        result["events"] = events()
finally:
    for proc in reversed(processes):
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
raise SystemExit(0 if result["status"] in ("passed", "pending-pixel-check") else 1)
