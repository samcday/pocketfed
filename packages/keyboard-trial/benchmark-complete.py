#!/usr/bin/python3
"""Measure the current-word API on a private bus against the pinned corpus."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from gi.repository import Gio, GLib

CASES = {
    "helo": "hello", "teh": "the", "recieve": "receive", "thier": "their",
    "wrold": "world", "writting": "writing", "comming": "coming",
    "becuase": "because", "tomorow": "tomorrow", "adress": "address",
    "hell": "hello", "worl": "world", "a": None, "he": None,
    "hello": None, "cat": None, "linux": None, "café": None, "zzqv": None,
}
NAME = "org.verbisage.Dictionary"
OBJECT = "/org/verbisage/Dictionary"
IFACE = "org.verbisage.Dictionary1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon", required=True, type=Path)
    parser.add_argument("--dictionary", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assert args.rounds > 0
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    with tempfile.TemporaryDirectory(prefix="complete-benchmark-") as temporary:
        config = Path(temporary) / "config.toml"
        config.write_text('backend="patricia"\n[backends.patricia]\ntype="patricia"\npath='
                          + json.dumps(str(args.dictionary.resolve())) + '\n')
        start = time.perf_counter()
        process = subprocess.Popen([str(args.daemon.resolve()), "--mode", "dbus", "--config", str(config)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                assert process.poll() is None, "daemon exited"
                owner = connection.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                             "org.freedesktop.DBus", "NameHasOwner",
                                             GLib.Variant("(s)", (NAME,)), None,
                                             Gio.DBusCallFlags.NONE, 1000, None)
                if owner.unpack()[0]:
                    break
                time.sleep(0.01)
            else:
                raise RuntimeError("daemon did not acquire bus name")
            results = {"startup_ms": (time.perf_counter() - start) * 1000,
                       "daemon_sha256": hashlib.sha256(args.daemon.read_bytes()).hexdigest(),
                       "dictionary_sha256": hashlib.sha256(args.dictionary.read_bytes()).hexdigest(),
                       "rounds": args.rounds,
                       "scope": "Private D-Bus Complete round trips; excludes 60 ms frontend debounce and physical input/display. OS page cache not flushed.",
                       "cases": {}}
            for word, target in CASES.items():
                timings, first = [], None
                for _ in range(args.rounds):
                    start = time.perf_counter()
                    reply = connection.call_sync(NAME, OBJECT, IFACE, "Complete",
                                                 GLib.Variant("(sus)", (word, 6, "en_US")), None,
                                                 Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
                    timings.append((time.perf_counter() - start) * 1000)
                    if first is None:
                        first = reply
                    assert reply == first, f"non-deterministic results for {word}"
                candidates = [text for text, score in first if text.casefold() != word.casefold()]
                ordered = sorted(timings)
                row = {"results": first, "target": target,
                       "target_rank_excluding_literal": candidates.index(target) + 1 if target in candidates else None,
                       "median_ms": statistics.median(timings),
                       "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
                       "max_ms": max(timings)}
                results["cases"][word] = row
                print(word, candidates, "target rank", row["target_rank_excluding_literal"], flush=True)
            args.output.write_text(json.dumps(results, indent=2) + "\n")
            # The reported user regression and existing accepted workflows.
            for word in ("helo", "teh", "hell"):
                rank = results["cases"][word]["target_rank_excluding_literal"]
                assert rank is not None and rank <= 2, (word, rank)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
