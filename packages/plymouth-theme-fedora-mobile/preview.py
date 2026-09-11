#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Render the actual installed Plymouth plugin in a disposable Xvfb namespace."""
import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def run(*args):
    subprocess.run(args, check=True)


def type_text(text):
    """Send synthetic, non-secret test input only to the private Xvfb server."""
    x = ctypes.CDLL("libX11.so.6")
    xt = ctypes.CDLL("libXtst.so.6")
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    display = x.XOpenDisplay(b":99")
    assert display
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    root = x.XDefaultRootWindow(display)
    children = ctypes.POINTER(ctypes.c_ulong)()
    count, returned_root, parent = ctypes.c_uint(), ctypes.c_ulong(), ctypes.c_ulong()
    x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                           ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                           ctypes.POINTER(ctypes.c_uint)]
    x.XQueryTree(display, root, ctypes.byref(returned_root), ctypes.byref(parent),
                 ctypes.byref(children), ctypes.byref(count))
    class Attributes(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("x", "y", "width", "height", "border", "depth")] + [
            ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
            ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
            ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
            ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
            ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
            ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
            ("all_events", ctypes.c_long), ("your_events", ctypes.c_long),
            ("do_not_propagate", ctypes.c_long), ("override_redirect", ctypes.c_int),
            ("screen", ctypes.c_void_p)]
    x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Attributes)]
    visible = []
    for child in children[:count.value]:
        attributes = Attributes()
        x.XGetWindowAttributes(display, child, ctypes.byref(attributes))
        if attributes.map_state == 2:
            visible.append((attributes.width * attributes.height, child))
    assert visible, "Plymouth has no viewable Xvfb window"
    x.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    x.XSetInputFocus(display, max(visible)[1], 1, 0)
    x.XStringToKeysym.argtypes, x.XStringToKeysym.restype = [ctypes.c_char_p], ctypes.c_ulong
    x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    for letter in text:
        keysym = x.XStringToKeysym(b"Return" if letter == "\n" else letter.encode())
        key = x.XKeysymToKeycode(display, keysym)
        xt.XTestFakeKeyEvent(display, key, 1, 0)
        xt.XTestFakeKeyEvent(display, key, 0, 0)
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x.XSync(display, 0)
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay(display)


def inside(geometry, scale):
    from PIL import ImageChops, ImageGrab
    output = Path("/tmp/output")
    os.environ["DISPLAY"] = ":99"
    log = (output / "xvfb.log").open("w")
    # Disable GLX: this validates software pixel rendering with no GPU device.
    xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", geometry + "x24",
                             "-nolisten", "tcp", "-extension", "GLX"], stdout=log, stderr=log)
    daemon = None
    try:
        time.sleep(.5)
        assert xvfb.poll() is None
        daemon_log = (output / "daemon.log").open("w")
        daemon = subprocess.Popen(["plymouthd", "--no-daemon", "--debug", "--no-boot-log",
            "--debug-file=/tmp/output/plymouth.log", "--pid-file=/run/plymouth.pid",
            "--kernel-command-line=quiet splash plymouth.splash=fedora-mobile "
            f"plymouth.force-scale={scale} plymouth.ignore-serial-consoles"],
            stdout=daemon_log, stderr=daemon_log)
        for _ in range(30):
            if subprocess.run(["plymouth", "--ping"], capture_output=True).returncode == 0:
                break
            time.sleep(.1)
        run("plymouth", "show-splash")

        def capture(name):
            time.sleep(.35)
            result = ImageGrab.grab(xdisplay=":99")
            result.save(output / f"{name}.png")
            assert result.convert("RGB").getbbox(), f"empty {name} render"
            return result

        first = capture("boot")
        second = capture("boot-next-frame")
        assert ImageChops.difference(first, second).getbbox(), "animation is frozen"
        run("plymouth", "display-message", "--text=Checking storage...")
        capture("message")
        run("plymouth", "hide-message", "--text=Checking storage...")
        for command, prompt, answer, filename in (
            ("ask-for-password", "Unlock encrypted storage:", "sample", "password"),
            ("ask-question", "Recovery response:", "continue", "question"),
        ):
            client = subprocess.Popen(["plymouth", command, "--prompt=" + prompt], stdout=subprocess.PIPE)
            time.sleep(.25)
            type_text(answer)
            capture(filename)
            type_text("\n")
            stdout, _ = client.communicate(timeout=5)
            assert stdout.decode().strip() == answer, (command, stdout)
        for mode in ("updates", "system-upgrade", "firmware-upgrade", "system-reset"):
            run("plymouth", "change-mode", "--" + mode)
            run("plymouth", "system-update", "--progress=42")
            capture(mode)
        run("plymouth", "change-mode", "--boot-up")
        run("plymouth", "deactivate")
        run("plymouth", "reactivate")
        capture("reactivated")
        run("plymouth", "change-mode", "--shutdown")
        capture("shutdown")
        run("plymouth", "change-mode", "--reboot")
        capture("reboot")
        print(f"PASS actual two-step plugin: {geometry} scale={scale}, animation, message, "
              "password/question input, four update modes, reactivate, shutdown/reboot")
    finally:
        subprocess.run(["plymouth", "quit"], capture_output=True)
        if daemon:
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
        xvfb.terminate()
        xvfb.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--geometry", default="1080x2220")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        inside(args.geometry, args.scale)
    else:
        source = Path(__file__).resolve().parent
        output = args.output.resolve()
        if output.exists():
            parser.error("output must not exist")
        theme = output / "theme"
        captures = output / "renders"
        captures.mkdir(parents=True)
        run(sys.executable, str(source / "generate-assets.py"), str(theme))
        shutil.copyfile(source / "fedora-mobile.plymouth", theme / "fedora-mobile.plymouth")
        (theme / "keymap-render.png").symlink_to("../spinner/keymap-render.png")
        run("bwrap", "--unshare-all", "--uid", "0", "--gid", "0", "--ro-bind", "/", "/",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/run", "--tmpfs", "/tmp",
            "--tmpfs", "/usr/share/plymouth/themes", "--bind", str(captures), "/tmp/output",
            "--ro-bind", str(theme), "/usr/share/plymouth/themes/fedora-mobile",
            "--ro-bind", "/usr/share/plymouth/themes/spinner", "/usr/share/plymouth/themes/spinner",
            "--ro-bind", str(Path(__file__).resolve()), "/tmp/preview.py",
            "--", sys.executable, "/tmp/preview.py", "/tmp/output", "--inside",
            "--geometry", args.geometry, "--scale", str(args.scale))
