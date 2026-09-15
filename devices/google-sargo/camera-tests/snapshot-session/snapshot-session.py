#!/usr/bin/env python3
"""One bounded GNOME Snapshot capture session producing one saved JPEG.

This is the post-readiness half of the Sargo Snapshot trial. It is meant to be
the single command of ``wait-for-ready.py``: the gate first obtains a fresh
Volume Up authorization (and keeps monitoring Volume Down), then starts this
helper. The helper brings up a standalone Phoc session, PipeWire and
WirePlumber (whose libcamera monitor publishes the camera node), launches
``snapshot`` with a private ``HOME``/XDG environment, injects the
``win.take-picture`` accelerator (``t``) with ``wtype`` until a JPEG lands,
strictly decodes it and checks the camera release gate.

It reuses the reviewed helpers in ``../libcamera-session/libcamera-session.py``
(``Reporter``, ``power_gate``, ``identify``, result writing and scoped
process-tree cleanup) instead of copying that framework, exactly as
``qcam-session`` does.

Source-verified contract (cited in
``out/camera-snapshot-research-20260915/report.md``)
----------------------------------------------------

- Snapshot 51.beta's in-tree ``aperture`` library enumerates cameras with
  GStreamer's PipeWire device provider, filtering ``Video/Source`` nodes; the
  portal is optional and every non-``NotAllowed`` portal error falls back to
  the direct provider. Snapshot reacts to ``device-added``, so it may start
  before or after the node appears.
- WirePlumber 0.5.14's ``monitor.libcamera`` publishes the node named
  ``libcamera_input.<device>``. The default here is the stable rear sensor
  ``/base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a``; enumeration alone does not
  open a stream, so it does not itself capture.
- The shutter action is ``win.take-picture`` with accelerator ``t``
  (``src/application.rs``). phoc 0.57 allows input when started without
  ``-S/--shell`` and implements ``zwp_virtual_keyboard_v1``, so ``wtype t``
  can drive it.
- Snapshot saves to ``g_get_user_special_dir(Pictures)/Camera`` and needs a
  valid ``~/.config/user-dirs.dirs``; ``GSETTINGS_BACKEND=memory`` keeps the
  unwrapped ``last-camera-id`` write safe without dconf or a session bus. No
  EXIF orientation is written by this version's ``jpegenc``.

The launcher does not start the camera pipeline before the gate authorizes
it: the gate owns that ordering, and this helper is only ever the gate's
single command.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CAMERA_TESTS = HERE.parent
SESSION_HELPER = CAMERA_TESTS / "libcamera-session" / "libcamera-session.py"

# Importing the reviewed helper has no side effects: its main() is guarded by
# ``if __name__ == "__main__"``. Its functions are reused unchanged.
_SESSION_SPEC = importlib.util.spec_from_file_location(
    "pocketfed_libcamera_session", SESSION_HELPER)
session = importlib.util.module_from_spec(_SESSION_SPEC)
_SESSION_SPEC.loader.exec_module(session)

PREFIX = "pocketfed-snapshot-session"
# Reporter.state() formats its module-level PREFIX; present this session's.
session.PREFIX = PREFIX

SessionError = session.SessionError
Cancelled = session.Cancelled
Reporter = session.Reporter
power_gate = session.power_gate
identify = session.identify
terminate_process_tree = session.terminate_process_tree
write_result = session.write_result

# libcamera_input.<stable rear sensor path with separators flattened>.
DEFAULT_CAMERA_NODE = "libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_0_camera_1a"
DEFAULT_SOFTISP_MODE = "gpu"
DEFAULT_SOCKET = "pocketfed-snapshot"
DEFAULT_SETTLE = 8
DEFAULT_SHUTTER_RETRIES = 5
DEFAULT_RETRY_INTERVAL = 3
DEFAULT_STARTUP_TIMEOUT = 20
DEFAULT_NODE_TIMEOUT = 30
DEFAULT_TIMEOUT = 180
SOFTISP_MODES = ("gpu", "cpu")
NODE_POLL_INTERVAL = 0.25
JPEG_POLL_INTERVAL = 0.05

# Start-of-frame markers carrying geometry: SOF0..SOF15 except DHT/JPG/DAC.
SOF_MARKERS = frozenset({
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
})


def start_process(command, log_path, env):
    """Start an owned child in this process group and log it privately."""
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    stream = os.fdopen(descriptor, "w")
    process = subprocess.Popen(command, env=env, stdout=stream,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return process, stream


def close_stream(stream):
    if stream is None:
        return
    try:
        stream.close()
    except OSError:
        pass


def resolve_tool(value):
    """Resolve an option to an executable the same way everywhere.

    A bare name (for example the default ``snapshot``) is found on PATH; an
    explicit path is used only when it is a file. Returns None when neither
    exists, so callers can report a missing tool instead of failing at exec
    time. An explicit file need not carry the execute bit (``power-state.py``
    is invoked through the interpreter), so a permission error surfaces
    through the normal bounded failure path.
    """
    text = str(value)
    if os.sep in text:
        return text if Path(text).is_file() else None
    return shutil.which(text)


def refuse_existing_compositor():
    """Refuse to start when another compositor already owns the DRM seat."""
    running = []
    for path in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = path.read_text().strip()
        except OSError:
            continue
        if name in {"phoc", "phosh"}:
            running.append((path.parent.name, name))
    if running:
        detail = ", ".join(f"{name}({pid})" for pid, name in running)
        raise SessionError(f"existing compositor running: {detail}")


def session_env(runtime):
    """Standalone DRM session environment, private to this run's runtime dir."""
    env = dict(os.environ)
    env.update({
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_SESSION_TYPE": "wayland",
        "WLR_BACKENDS": "drm,libinput",
        "WLR_RENDERER": "gles2",
        "LIBSEAT_BACKEND": "noop",
    })
    for key in ("WAYLAND_DISPLAY", "DISPLAY", "LD_PRELOAD",
                "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(key, None)
    return env


def libcamera_env(runtime, softisp_mode, libcamera_log):
    """Session environment plus the libcamera knobs the pipeline needs."""
    env = session_env(runtime)
    env["LIBCAMERA_SOFTISP_MODE"] = softisp_mode
    if libcamera_log:
        env["LIBCAMERA_LOG_LEVELS"] = libcamera_log
    return env


DEFAULT_FRONT_CAMERA_NODE = "libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_1_camera_1a"
SYSTEM_HEAP = "/dev/dma_heap/system"

# Executed by `unshare --mount`: hide every DMA heap except the system heap so
# libcamera's software ISP (running inside WirePlumber) cannot pick the small
# CMA heaps that fail allocation on Sargo. Mirrors ../cam-system-heap.
HEAP_NAMESPACE_SCRIPT = (
    'mount -t tmpfs -o mode=0700 tmpfs /dev/dma_heap && '
    'mknod -m 0600 /dev/dma_heap/system c "$1" "$2" && shift 2 && exec "$@"'
)


def write_wireplumber_rules(config_home, disabled_nodes):
    """Write a private WirePlumber fragment that disables the given nodes.

    WirePlumber 0.5 applies ``monitor.libcamera.rules`` to node properties
    before ``create-node.lua`` runs, so a matched ``node.disabled = true`` means
    the node is never exported and Snapshot cannot pick it as its default.
    """
    fragment_dir = config_home / "wireplumber" / "wireplumber.conf.d"
    fragment_dir.mkdir(mode=0o700, parents=True)
    matches = "".join(
        f'    {{ matches = [ {{ node.name = "{name}" }} ]\n'
        f'      actions = {{ update-props = {{ node.disabled = true }} }} }}\n'
        for name in disabled_nodes)
    text = "monitor.libcamera.rules = [\n" + matches + "]\n"
    path = fragment_dir / "90-pocketfed-snapshot-session.conf"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    return path


def system_heap_command(command, heap=SYSTEM_HEAP, unshare="unshare"):
    """Wrap a command so it sees only the system DMA heap (root only)."""
    try:
        info = os.stat(heap)
    except OSError as error:
        raise SessionError(f"system DMA heap unavailable: {heap}: {error}") from error
    if not stat.S_ISCHR(info.st_mode):
        raise SessionError(f"{heap} is not a character device")
    return [unshare, "--mount", "--propagation", "private", "--", "sh", "-ec",
            HEAP_NAMESPACE_SCRIPT, "pocketfed-snapshot-heap",
            str(os.major(info.st_rdev)), str(os.minor(info.st_rdev)), *command]


NO_BUS_ADDRESS = "unix:path=/nonexistent/pocketfed-snapshot-no-bus"


def snapshot_env(runtime, socket, home, softisp_mode, libcamera_log,
                 no_dbus=False):
    """Snapshot's private Wayland, HOME and GSettings environment.

    With ``no_dbus`` the bus address points at a socket that cannot exist, so
    Snapshot's portal request fails immediately (not ``NotAllowed``) and it
    falls back to the direct PipeWire device provider instead of letting a
    session bus auto-activate xdg-desktop-portal, whose camera remote is not
    granted by this standalone WirePlumber.
    """
    env = libcamera_env(runtime, softisp_mode, libcamera_log)
    env.update({
        "HOME": str(home),
        "WAYLAND_DISPLAY": socket,
        "GDK_BACKEND": "wayland",
        "GSETTINGS_BACKEND": "memory",
    })
    if no_dbus:
        env["DBUS_SESSION_BUS_ADDRESS"] = NO_BUS_ADDRESS
    return env


def build_snapshot_command(snapshot, dbus):
    # A private session bus is optional: Snapshot's portal path degrades to the
    # direct PipeWire provider, so fall back to no bus when the wrapper is absent.
    if dbus is not None:
        return [dbus, "--", snapshot]
    return [snapshot]


def wait_for_socket(path, process, timeout, clock=time.monotonic):
    """Wait for Phoc's Wayland socket to appear as a real Unix socket.

    A regular file is not a listening socket, so require S_ISSOCK rather than
    mere existence. Phoc creates it via wl_display_add_socket under
    XDG_RUNTIME_DIR (source: phoc src/server.c).
    """
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            mode = path.stat().st_mode
        except OSError:
            mode = None
        if mode is not None and stat.S_ISSOCK(mode):
            return
        if process.poll() is not None:
            raise SessionError(
                f"phoc exited with {process.returncode} before creating a socket")
        time.sleep(0.05)
    raise SessionError(f"phoc socket {path.name} did not appear within {timeout:g}s")


def find_camera_node(document, prefix):
    """Return the first Video/Source node whose name starts with ``prefix``.

    pw-dump's JSON is parsed, never grepped. Returns None when no entry matches.
    """
    if not isinstance(document, list):
        return None
    for entry in document:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "PipeWire:Interface:Node":
            continue
        info = entry.get("info")
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict):
            continue
        if props.get("media.class") != "Video/Source":
            continue
        name = props.get("node.name")
        if isinstance(name, str) and name.startswith(prefix):
            return {"id": entry.get("id"), "name": name, "props": props}
    return None


def wait_for_camera_node(args, processes, pw_dump, env, deadline, clock=time.monotonic):
    """Poll pw-dump until WirePlumber's libcamera node appears.

    ``processes`` is a list of (name, Popen) that must stay alive; pw-dump is
    retried because it also fails while PipeWire is still coming up.
    """
    end = min(deadline, clock() + args.node_timeout)
    last_code = None
    while clock() < end:
        for name, process in processes:
            if process.poll() is not None:
                raise SessionError(
                    f"{name} exited with {process.returncode} before the camera node")
        try:
            result = subprocess.run(
                [pw_dump], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=min(10.0, max(0.1, end - clock())), check=False)
            last_code = result.returncode
        except subprocess.TimeoutExpired:
            last_code = None
            continue
        if result.returncode == 0:
            try:
                document = json.loads(result.stdout)
            except json.JSONDecodeError:
                document = None
            node = find_camera_node(document, args.camera_node)
            if node is not None:
                return node, last_code
        if clock() >= end:
            break
        time.sleep(min(NODE_POLL_INTERVAL, max(0.0, end - clock())))
    raise SessionError(
        f"camera node {args.camera_node!r} did not appear within {args.node_timeout:g}s")


def newest_jpeg(camera_dir):
    """Return the newest ``*.jpeg`` in the Camera directory, or None."""
    newest = None
    try:
        entries = list(camera_dir.glob("*.jpeg"))
    except OSError:
        return None
    for path in entries:
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or modified >= newest[0]:
            newest = (modified, path)
    return None if newest is None else newest[1]


def wait_for_jpeg(camera_dir, interval, deadline, clock=time.monotonic):
    """Wait up to ``interval`` for any JPEG to appear."""
    end = min(deadline, clock() + interval)
    while True:
        photo = newest_jpeg(camera_dir)
        if photo is not None:
            return photo
        if clock() >= end:
            return None
        time.sleep(min(JPEG_POLL_INTERVAL, max(0.0, end - clock())))


def wait_for_stable_jpeg(camera_dir, interval, deadline, clock=time.monotonic):
    """Return a JPEG once it exists and its size is unchanged over one poll.

    A file that appears during the interval is not accepted yet; the caller's
    next shutter press tries again, which also avoids copying a half-written
    original.
    """
    appeared = wait_for_jpeg(camera_dir, interval, deadline, clock)
    if appeared is None:
        return None
    try:
        size = appeared.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    pause = min(interval, max(0.0, deadline - clock()))
    if pause:
        time.sleep(pause)
    again = newest_jpeg(camera_dir)
    try:
        if again == appeared and again.stat().st_size == size:
            return appeared
    except OSError:
        return None
    return None


def run_shutter(args, wtype, env, camera_dir, snapshot, deadline, reporter,
                clock=time.monotonic):
    """Press ``t`` until a stable JPEG lands, recording presses and last code."""
    presses = 0
    last_code = None
    while presses < args.shutter_retries:
        if clock() >= deadline:
            raise SessionError("session timeout before a JPEG was saved")
        if snapshot.poll() is not None:
            raise SessionError(
                f"snapshot exited with {snapshot.returncode} before saving a JPEG")
        try:
            result = subprocess.run(
                [wtype, "t"], env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                timeout=min(10.0, max(0.1, deadline - clock())), check=False)
            last_code = result.returncode
        except subprocess.TimeoutExpired:
            last_code = None
        presses += 1
        reporter.state("shutter", f"press={presses}")
        photo = wait_for_stable_jpeg(camera_dir, args.retry_interval, deadline, clock)
        if photo is not None:
            return presses, photo, last_code
    return presses, None, last_code


def jpeg_geometry(data):
    """Parse width/height and validate SOI/EOI/SOF without any third party.

    Used when ``magick`` is unavailable or cannot decode the copy. The original
    JPEG is never opened or rewritten by this function.
    """
    if not data.startswith(b"\xff\xd8"):
        raise SessionError("not a JPEG: missing SOI marker")
    if b"\xff\xd9" not in data[-32:]:
        raise SessionError("truncated JPEG: missing EOI marker")
    index = 2
    length = len(data)
    while index + 3 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 1 >= length:
            break
        segment = (data[index] << 8) | data[index + 1]
        if marker in SOF_MARKERS:
            if index + 6 >= length:
                break
            height = (data[index + 3] << 8) | data[index + 4]
            width = (data[index + 5] << 8) | data[index + 6]
            if width and height:
                return width, height
            break
        index += segment
    raise SessionError("no JPEG SOF segment found")


def measure_jpeg(magick, path):
    """Return (width, height, method, magick code); prefer magick, else Python."""
    if magick is not None:
        try:
            geometry = identify(magick, path)
        except (SessionError, OSError, subprocess.SubprocessError):
            geometry = None
        if geometry:
            match = re.search(r"JPEG\s+(\d+)\s+(\d+)", geometry)
            if match:
                return int(match.group(1)), int(match.group(2)), "magick", 0
    width, height = jpeg_geometry(path.read_bytes())
    return width, height, "python", None


def stop_process(process, grace=2.0):
    """SIGTERM then SIGKILL one owned child, bounded."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def teardown(children):
    """Stop children in reverse start order, then sweep with the reviewed helper.

    Snapshot is stopped first, Phoc last. The scoped ``terminate_process_tree``
    (from the sibling helper) then catches any descendant left in this helper's
    group; no process-name-wide kills.
    """
    for _name, process, _stream in reversed(children):
        stop_process(process)
    remaining = []
    for _name, process, _stream in children:
        remaining.extend(terminate_process_tree(process))
    for _name, _process, stream in children:
        close_stream(stream)
    return sorted(set(remaining))


def prepare_home(home):
    """Create HOME with the mandatory GLib pictures special dir."""
    camera_dir = home / "Pictures" / "Camera"
    camera_dir.mkdir(mode=0o700, parents=True)
    config_dir = home / ".config"
    config_dir.mkdir(mode=0o700, parents=True)
    user_dirs = config_dir / "user-dirs.dirs"
    descriptor = os.open(user_dirs, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, b'XDG_PICTURES_DIR="$HOME/Pictures"\n')
    finally:
        os.close(descriptor)
    return camera_dir


def resolve_tools(args):
    """Resolve every required tool; magick and the bus wrapper stay optional."""
    resolved = {}
    missing = []
    for key in ("phoc", "pipewire", "wireplumber", "snapshot", "wtype",
                "pw_dump", "power_state"):
        path = resolve_tool(getattr(args, key))
        if path is None:
            missing.append(f"{key}={getattr(args, key)}")
        resolved[key] = path
    if missing:
        raise SessionError("missing required tools: " + ", ".join(missing))
    resolved["magick"] = resolve_tool(args.magick)
    resolved["dbus"] = None if args.no_dbus else shutil.which("dbus-run-session")
    resolved["unshare"] = None
    if args.private_system_heap:
        resolved["unshare"] = resolve_tool(args.unshare)
        if resolved["unshare"] is None:
            raise SessionError(f"missing required tools: unshare={args.unshare}")
    return resolved


def disabled_nodes(value):
    """Default to the front camera; an empty entry disables nothing."""
    if value is None:
        return [DEFAULT_FRONT_CAMERA_NODE]
    return [name for name in value if name]


def run_session(args, reporter):
    args.disable_node = disabled_nodes(args.disable_node)
    output = Path(args.output).resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    runtime = output / "runtime"
    runtime.mkdir(mode=0o700)
    home = output / "home"
    home.mkdir(mode=0o700)
    camera_dir = prepare_home(home)
    socket_path = runtime / args.socket
    clock = time.monotonic
    deadline = clock() + args.timeout

    report = {
        "status": "failed",
        "kernel": os.uname().release,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "camera_node": args.camera_node,
        "camera_node_id": None,
        "camera_node_name": None,
        "softisp_mode": args.softisp_mode,
        "libcamera_log": args.libcamera_log,
        "socket": args.socket,
        "settle": args.settle,
        "shutter_retries": args.shutter_retries,
        "retry_interval": args.retry_interval,
        "startup_timeout": args.startup_timeout,
        "node_timeout": args.node_timeout,
        "timeout": args.timeout,
        "shutter_presses": 0,
        "source_jpeg": None,
        "photo": None,
        "geometry": None,
        "width": None,
        "height": None,
        "geometry_method": None,
        "camera_attempted": False,
        "camera_released": None,
        "release_error": None,
        "dbus_run_session": False,
        "wireplumber_rules": None,
        "private_system_heap": False,
        "disabled_nodes": list(args.disable_node),
        "phoc": None,
        "pipewire": None,
        "wireplumber": None,
        "snapshot": None,
        "wtype": None,
        "pw_dump": None,
        "magick": None,
        "remaining_processes": [],
        "error": None,
    }

    cleanup_started = False
    cancel_signum = None

    def handler(signum, _frame):
        nonlocal cancel_signum
        if cleanup_started:
            return
        cancel_signum = signum
        raise Cancelled(signum)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    status = None
    primary_error = None
    camera_attempted = False
    released = None
    release_error = None
    power_state = None
    children = []
    survivors = []
    last_wtype = None
    last_pw_dump = None

    try:
        reporter.state("preflight")
        tools = resolve_tools(args)
        power_state = tools["power_state"]

        reporter.state("release-gate", "before")
        power_gate(Path(power_state), output / "power-before.json")

        if not args.allow_existing_compositor:
            refuse_existing_compositor()

        reporter.state("compositor-start", tools["phoc"])
        phoc, phoc_stream = start_process(
            [tools["phoc"], "--socket", args.socket, "--no-xwayland"],
            output / "phoc.log", session_env(runtime))
        children.append(("phoc", phoc, phoc_stream))
        wait_for_socket(socket_path, phoc,
                        min(args.startup_timeout, max(0.0, deadline - clock())))
        reporter.state("compositor-ready", args.socket)

        # From here on the camera pipeline may touch the devices, so the after
        # release gate must run even if it fails before Snapshot starts.
        reporter.state("pipeline-start")
        camera_attempted = True
        report["camera_attempted"] = True
        pipeline = libcamera_env(runtime, args.softisp_mode, args.libcamera_log)
        pipewire, pipewire_stream = start_process(
            [tools["pipewire"]], output / "pipewire.log", pipeline)
        children.append(("pipewire", pipewire, pipewire_stream))
        wireplumber_env = dict(pipeline)
        if args.disable_node:
            config_home = runtime / "config"
            config_home.mkdir(mode=0o700)
            rules = write_wireplumber_rules(config_home, args.disable_node)
            report["wireplumber_rules"] = str(rules)
            wireplumber_env["XDG_CONFIG_HOME"] = str(config_home)
        wireplumber_command = [tools["wireplumber"]]
        if args.private_system_heap:
            wireplumber_command = system_heap_command(
                wireplumber_command, unshare=tools["unshare"])
            report["private_system_heap"] = True
        wireplumber, wireplumber_stream = start_process(
            wireplumber_command, output / "wireplumber.log", wireplumber_env)
        children.append(("wireplumber", wireplumber, wireplumber_stream))

        reporter.state("camera-node", args.camera_node)
        node, last_pw_dump = wait_for_camera_node(
            args, [("pipewire", pipewire), ("wireplumber", wireplumber)],
            tools["pw_dump"], pipeline, deadline)
        report["camera_node_id"] = node["id"]
        report["camera_node_name"] = node["name"]
        reporter.state("camera-node-ready", f"id={node['id']} name={node['name']}")

        command = build_snapshot_command(tools["snapshot"], tools["dbus"])
        report["dbus_run_session"] = tools["dbus"] is not None
        reporter.state("snapshot-start", tools["snapshot"])
        snapshot, snapshot_stream = start_process(
            command, output / "snapshot.log",
            snapshot_env(runtime, args.socket, home, args.softisp_mode,
                         args.libcamera_log, args.no_dbus))
        children.append(("snapshot", snapshot, snapshot_stream))

        if args.settle > 0:
            pause = min(deadline, clock() + args.settle) - clock()
            if pause > 0:
                reporter.state("settling", f"{args.settle:g}s")
                time.sleep(pause)
        if clock() >= deadline:
            raise SessionError("session timeout before the shutter")

        reporter.state("shutter")
        presses, photo, last_wtype = run_shutter(
            args, tools["wtype"],
            snapshot_env(runtime, args.socket, home, args.softisp_mode,
                         args.libcamera_log, args.no_dbus),
            camera_dir, snapshot, deadline, reporter)
        report["shutter_presses"] = presses
        if photo is None:
            raise SessionError(
                f"snapshot saved no JPEG after {presses} shutter press(es)")

        report["source_jpeg"] = str(photo)
        destination = output / "photo.jpeg"
        shutil.copyfile(photo, destination)
        os.chmod(destination, 0o600)

        width, height, method, magick_code = measure_jpeg(tools["magick"], destination)
        report["magick"] = magick_code
        report["width"] = width
        report["height"] = height
        report["geometry"] = f"JPEG {width} {height}"
        report["geometry_method"] = method
        report["photo"] = str(destination)
        status = "passed"
    except Cancelled as cancel:
        cancel_signum = cancel.signum
        status = "cancelled"
        primary_error = f"signal {cancel.signum}"
        reporter.state("cancelled", f"signal-{cancel.signum}")
    except (SessionError, OSError, subprocess.SubprocessError) as error:
        # SubprocessError (for example a tool TimeoutExpired) must become a
        # recorded failure, never an uncaught traceback.
        status = "failed"
        primary_error = str(error)
        reporter.state("failed", str(error))
    finally:
        # Block further cancellation while cleaning up so repeated Volume Down
        # cannot skip the release gate or the result write.
        previous_mask = signal.pthread_sigmask(
            signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        cleanup_started = True
        try:
            survivors = teardown(children)
            report["remaining_processes"] = survivors
            for name, process, _stream in children:
                report[name] = process.returncode
            report["wtype"] = last_wtype
            report["pw_dump"] = last_pw_dump
            if camera_attempted and power_state is not None:
                reporter.state("release-gate", "after")
                try:
                    power_gate(Path(power_state), output / "power-after.json")
                    released = True
                except (SessionError, OSError, subprocess.SubprocessError) as error:
                    released = False
                    release_error = str(error)
                    reporter.warn(f"post-release-gate-failed {release_error}")
            report["status"] = status or "failed"
            report["camera_released"] = released
            report["release_error"] = release_error
            if primary_error is not None:
                report["error"] = primary_error
            elif release_error is not None:
                report["error"] = release_error
            elif survivors:
                report["error"] = ("owned processes survived cleanup: "
                                   + ",".join(str(pid) for pid in survivors))
            if report["status"] == "passed":
                # Never return success without a confirmed release or while an
                # owned process survived cleanup.
                if survivors:
                    report["status"] = "failed"
                    if report["error"] is None:
                        report["error"] = ("owned processes survived cleanup: "
                                           + ",".join(str(pid) for pid in survivors))
                elif released is not True:
                    report["status"] = "failed"
                    report["error"] = release_error or "camera release unconfirmed"
            write_result(output / "result.json", report)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    if report["status"] == "passed":
        reporter.state("complete",
                       f"{report['photo']} geometry={report['geometry']} "
                       f"presses={report['shutter_presses']}")
        return 0
    if report["status"] == "cancelled":
        return 130 if cancel_signum == signal.SIGINT else 143
    return 1


def preflight(args):
    missing = [str(getattr(args, key)) for key in
               ("phoc", "pipewire", "wireplumber", "snapshot", "wtype",
                "pw_dump", "power_state")
               if resolve_tool(getattr(args, key)) is None]
    if missing:
        raise SessionError("missing required tools: " + ", ".join(missing))


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh private directory for this session's output")
    parser.add_argument("--camera-node", default=DEFAULT_CAMERA_NODE,
                        help="PipeWire node.name prefix to wait for "
                             "(default: stable rear libcamera node)")
    parser.add_argument("--softisp-mode", choices=SOFTISP_MODES,
                        default=DEFAULT_SOFTISP_MODE,
                        help="LIBCAMERA_SOFTISP_MODE for the pipeline "
                             "(default: gpu)")
    parser.add_argument("--libcamera-log", default=None,
                        help="optional LIBCAMERA_LOG_LEVELS value")
    parser.add_argument("--settle", type=int, default=DEFAULT_SETTLE,
                        help="seconds to let the window and stream start "
                             "before the first shutter press (0..120, default 8)")
    parser.add_argument("--shutter-retries", type=int, default=DEFAULT_SHUTTER_RETRIES,
                        help="shutter presses before giving up (1..60, default 5)")
    parser.add_argument("--retry-interval", type=int, default=DEFAULT_RETRY_INTERVAL,
                        help="seconds between shutter presses/polls "
                             "(1..60, default 3)")
    parser.add_argument("--startup-timeout", type=int, default=DEFAULT_STARTUP_TIMEOUT,
                        help="bound for the Phoc socket, seconds (1..120, default 20)")
    parser.add_argument("--node-timeout", type=int, default=DEFAULT_NODE_TIMEOUT,
                        help="bound for the camera node, seconds (1..300, default 30)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help="bound for the whole run, seconds (1..600, default 180)")
    parser.add_argument("--socket", default=DEFAULT_SOCKET,
                        help="private Wayland socket name under the runtime dir")
    parser.add_argument("--phoc", default="phoc", help="Phoc compositor to start")
    parser.add_argument("--pipewire", default="pipewire")
    parser.add_argument("--wireplumber", default="wireplumber")
    parser.add_argument("--snapshot", default="snapshot",
                        help="GNOME Snapshot executable to launch")
    parser.add_argument("--wtype", default="wtype",
                        help="virtual-keyboard tool that sends the shutter")
    parser.add_argument("--pw-dump", default="pw-dump",
                        help="PipeWire introspection tool used to find the node")
    parser.add_argument("--power-state", type=Path,
                        default=CAMERA_TESTS / "power-state.py")
    parser.add_argument("--magick", default="magick",
                        help="optional ImageMagick used to measure the JPEG")
    parser.add_argument("--allow-existing-compositor", action="store_true",
                        help="do not refuse when phoc/phosh is already running")
    parser.add_argument("--disable-node", action="append",
                        default=None, metavar="NODE_NAME",
                        help="WirePlumber libcamera node.name to disable before "
                             "Snapshot enumerates (repeatable; default: the "
                             "front camera, so the rear node is Snapshot's only "
                             "choice); pass an empty string to disable nothing")
    parser.add_argument("--private-system-heap", dest="private_system_heap",
                        action="store_true", default=True,
                        help="run WirePlumber in a mount namespace exposing only "
                             "/dev/dma_heap/system (default; needs root)")
    parser.add_argument("--no-private-system-heap", dest="private_system_heap",
                        action="store_false",
                        help="let libcamera choose any DMA heap")
    parser.add_argument("--unshare", default="unshare",
                        help="unshare tool for the private heap namespace")
    parser.add_argument("--no-dbus", action="store_true",
                        help="run snapshot without a session bus so its portal "
                             "request fails fast and it enumerates PipeWire "
                             "directly (a bus auto-activates xdg-desktop-portal, "
                             "whose camera remote this WirePlumber does not grant)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 0 <= args.settle <= 120:
        raise SystemExit("--settle must be 0..120")
    if not 1 <= args.shutter_retries <= 60:
        raise SystemExit("--shutter-retries must be 1..60")
    if not 1 <= args.retry_interval <= 60:
        raise SystemExit("--retry-interval must be 1..60")
    if not 1 <= args.startup_timeout <= 120:
        raise SystemExit("--startup-timeout must be 1..120")
    if not 1 <= args.node_timeout <= 300:
        raise SystemExit("--node-timeout must be 1..300")
    if not 1 <= args.timeout <= 600:
        raise SystemExit("--timeout must be 1..600")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.socket):
        raise SystemExit("--socket must be a simple socket name")
    if not args.camera_node or any(part.isspace() for part in args.camera_node):
        raise SystemExit("--camera-node must be a non-empty node name prefix")
    if args.libcamera_log is not None and any(
            part.isspace() for part in args.libcamera_log):
        raise SystemExit("--libcamera-log must not contain whitespace")
    if os.geteuid() != 0:
        raise SystemExit("run as root for the DRM seat and release gate")
    os.umask(0o077)
    try:
        preflight(args)
    except SessionError as error:
        print(f'{PREFIX}: failed "{error}"', file=sys.stderr)
        return 2
    if Path(args.output).exists():
        print(f'{PREFIX}: failed "output {args.output} already exists"',
              file=sys.stderr)
        return 2
    return run_session(args, Reporter(sys.stdout, Path(args.output) / "status"))


if __name__ == "__main__":
    raise SystemExit(main())
