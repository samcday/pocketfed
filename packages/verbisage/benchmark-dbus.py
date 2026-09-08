#!/usr/bin/python3
"""Measure actual Verbisage D-Bus round trips; run under dbus-run-session."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from gi.repository import Gio, GLib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--daemon", type=Path, required=True)
parser.add_argument("--dictionary", type=Path, required=True)
parser.add_argument("--rounds", type=int, default=30)
args = parser.parse_args()
connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
name = "org.verbisage.Dictionary"
path = "/org/verbisage/Dictionary"
interface = "org.verbisage.Dictionary1"


def call(method, signature, values):
    started = time.perf_counter_ns()
    result = connection.call_sync(name, path, interface, method, GLib.Variant(signature, values),
                                  None, Gio.DBusCallFlags.NONE, 5000, None)
    return (time.perf_counter_ns() - started) / 1e6, result.unpack()[0]


with tempfile.TemporaryDirectory(prefix="verbisage-benchmark-") as temporary:
    directory = Path(temporary)
    config = directory / "config.toml"
    config.write_text('backend = "patricia"\n[backends.patricia]\ntype = "patricia"\npath = "' +
                      str(args.dictionary.resolve()) + '"\n')
    started = time.perf_counter_ns()
    process = subprocess.Popen([str(args.daemon.resolve()), "--mode", "dbus", "--config", str(config)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            assert process.poll() is None, "daemon exited"
            owner = connection.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "NameHasOwner",
                                         GLib.Variant("(s)", (name,)), None,
                                         Gio.DBusCallFlags.NONE, 1000, None)
            if owner.unpack()[0]:
                break
            time.sleep(0.005)
        else:
            raise RuntimeError("daemon did not start")
        startup = (time.perf_counter_ns() - started) / 1e6
        cold, initial = call("QueryLimited", "(asasuusu)", (["a"], [], 0, 0, "en_US", 6))
        results = {"startup_ms": startup, "first_request_ms": cold,
                   "first_request": "QueryLimited(a, max=6)", "first_results": initial,
                   "cache_note": "Fresh daemon and dictionary mapping; OS page cache not flushed.",
                   "rounds": args.rounds, "requests": {}}
        cases = [("prefix:" + prefix, "QueryLimited", "(asasuusu)", ([prefix], [], 0, 0, "en_US", 6))
                 for prefix in ("a", "he", "hell")]
        cases += [("correction:" + word, "Suggest", "(sus)", (word, 6, "en_US"))
                  for word in ("teh", "helo")]
        for label, method, signature, values in cases:
            timings = []
            output = None
            for _ in range(args.rounds):
                elapsed, output = call(method, signature, values)
                timings.append(elapsed)
            ordered = sorted(timings)
            results["requests"][label] = {"median_ms": statistics.median(timings),
                "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
                "max_ms": max(timings), "results": output}
        print(json.dumps(results, indent=2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
