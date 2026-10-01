#!/usr/bin/env python3
"""Observe camera holders and runtime power without opening camera devices.

Run as root on sam-sargo. --require-released returns 0 only when all expected
devices are visible and suspended, with no holders or inaccessible processes.
This checks kernel runtime state, not electrical power consumption.
"""

import argparse
import errno
import json
import os
from pathlib import Path
import stat
import time


EXPECTED = {"imx363", "imx355", "lc898219xi"}


def read(path):
    try:
        return path.read_text().strip()
    except OSError as error:
        return {"error": str(error)}


def observe(sys_root=Path("/sys"), proc_root=Path("/proc")):
    nodes, identities, discovery_errors = {}, set(), []
    isp_paths, camera_names = set(), set()

    def add_node(device):
        identifier = read(device / "dev")
        try:
            major, minor = map(int, identifier.split(":"))
        except (AttributeError, ValueError):
            discovery_errors.append({"path": str(device), "dev": identifier})
            return
        nodes["/dev/" + device.name] = identifier
        identities.add(os.makedev(major, minor))

    for device in (sys_root / "class/video4linux").glob("*"):
        name = read(device / "name")
        if not isinstance(name, str):
            discovery_errors.append({"path": str(device), "name": name})
        elif name.split(" ")[0] in EXPECTED or name.startswith("msm_"):
            add_node(device)
            camera_names.add(name.split(" ")[0])
            if name.startswith("msm_"):
                isp_paths.add((device / "device").resolve())
    media_nodes = []
    for isp in isp_paths:
        # Media devices live beneath CAMSS, not necessarily /sys/class/media.
        for device in isp.glob("media[0-9]*"):
            add_node(device)
            media_nodes.append("/dev/" + device.name)

    power = {}
    for device in (sys_root / "bus/i2c/devices").glob("*"):
        name = read(device / "name")
        if isinstance(name, str) and name in EXPECTED:
            power[device.name] = {"name": name, **{
                field: read(device / "power" / field)
                for field in ("control", "runtime_status", "runtime_active_time",
                              "runtime_suspended_time", "autosuspend_delay_ms")
            }}

    holders, inaccessible, descriptor_errors = [], [], []
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except FileNotFoundError:
            continue  # Normal process exit during observation.
        except OSError as error:
            inaccessible.append({"pid": int(process.name), "error": str(error)})
            continue
        held = []
        for descriptor in descriptors:
            try:
                info = descriptor.stat()
                if stat.S_ISCHR(info.st_mode) and info.st_rdev in identities:
                    held.append({"fd": int(descriptor.name), "device": os.readlink(descriptor),
                                 "dev": f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"})
            except OSError as error:
                if error.errno not in (errno.ENOENT, errno.ESRCH):
                    descriptor_errors.append({"path": str(descriptor), "error": str(error)})
        if held:
            holders.append({"pid": int(process.name), "comm": read(process / "comm"),
                            "descriptors": held})

    missing_power = sorted(EXPECTED - {d["name"] for d in power.values()})
    missing_nodes = sorted(EXPECTED - camera_names)
    unknown = []
    if os.geteuid() != 0:
        unknown.append("root process visibility is required")
    if missing_power or missing_nodes or not media_nodes or not isp_paths:
        unknown.append("camera discovery is incomplete")
    if discovery_errors or inaccessible or descriptor_errors:
        unknown.append("some devices or process descriptors could not be inspected")
    if any(not isinstance(d["runtime_status"], str) or
           d["runtime_status"] not in {"active", "suspended", "suspending", "resuming"}
           for d in power.values()):
        unknown.append("runtime power state is unavailable")
    released = not unknown and not holders and all(
        d["runtime_status"] == "suspended" for d in power.values())
    return {"time_unix": time.time(), "kernel": os.uname().release,
            "boot_id": read(proc_root / "sys/kernel/random/boot_id"),
            "effective_uid": os.geteuid(), "power": power, "holders": holders,
            "camera_nodes": nodes, "media_nodes": sorted(media_nodes),
            "missing_power_devices": missing_power, "missing_camera_nodes": missing_nodes,
            "discovery_errors": discovery_errors, "descriptor_errors": descriptor_errors,
            "inaccessible_processes": len(inaccessible), "inaccessible_details": inaccessible,
            "release_status": "released" if released else "unknown" if unknown else "busy",
            "unknown_reasons": unknown}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-released", action="store_true")
    parser.add_argument("--timeout", type=float, default=0,
                        help="wait up to 60 seconds for release (requires --require-released)")
    args = parser.parse_args()
    if not 0 <= args.timeout <= 60 or (args.timeout and not args.require_released):
        parser.error("--timeout must be 0..60 and requires --require-released")
    started = time.monotonic()
    while True:
        report = observe()
        elapsed = time.monotonic() - started
        if not args.require_released or report["release_status"] == "released" or elapsed >= args.timeout:
            break
        time.sleep(min(.25, args.timeout - elapsed))
    report["waited_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, indent=2))
    if not args.require_released:
        return 0
    return {"released": 0, "busy": 1, "unknown": 2}[report["release_status"]]


if __name__ == "__main__":
    raise SystemExit(main())
