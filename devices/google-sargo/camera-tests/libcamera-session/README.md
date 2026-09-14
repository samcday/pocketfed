# libcamera-only capture session

A small replacement for the Megapixels visible session. It runs one bounded
`cam` session through the existing private-system-heap wrapper and produces a
settled RGB **JPEG** plus retained `cam --metadata`, with the release gate
around it. No desktop, no Megapixels, no new compositor.

This directory is new and self-contained. It depends only on the existing
sibling helpers `../cam-system-heap` and `../power-state.py`; it does not use
`visible-session/` or `native-bootstrap/`.

## Flow

```text
wait-for-ready.py                 # fresh Volume Up authorizes one command;
  └─ libcamera-session.py         # Volume Down still cancels the group
        ├─ power-state.py --require-released        (before)
        ├─ cam-system-heap -c REAR --stream role=still,width=1280,height=960,pixelformat=RGB888 \
        │                  --capture=<warmup+1> --metadata --file=<out>/frame-#.ppm [--display[=connector]]
        │     └─ warm-up frames are pruned as they complete, keeping only the newest few
        ├─ keep the final frame, convert to final.jpg, strictly decode PPM + JPEG
        ├─ power-state.py --require-released        (after)
        └─ result.json (private)
```

## Warm-up plan (source-verified, minimal)

The installed `cam` CLI (device `cam --help`) exposes `--capture N`, `--file`,
`--metadata`, `--stream` and optional `--display[=connector]`, but **no controls
and no way to discard frames or save only the last**. `python3-libcamera` is not
part of the installed `libcamera`/`IPA`/`tools`/`GStreamer` set, so `cam
--script` is not assumed.

The simplest bounded approach is therefore a single `cam` invocation with
`--capture warmup+1` (default `warmup=4`, so five frames: four discarded
in-effect, the fifth kept) while this helper deletes completed warm-up frames as
they appear. tmpfs holds at most `--keep` frames (default 2) during the run; only
the final PPM and the JPEG remain. The final frame is converted to JPEG with
ImageMagick, then both the RGB frame and the JPEG are fully decoded
(`magick -regard-warnings … null:`) and their geometry checked.

**Limit.** This bounds warm-up but cannot *prove* AE/AF convergence. If hardware
trials show the last frame is still not settled, the next step is a bounded
GStreamer `libcamerasrc`/appsink helper that drops buffers without writing
files, or a libcamera Python script if `python3-libcamera` is added. That is
deliberately not implemented speculatively here.

## Usage

Run it as the gate's single command (the gate must obtain Volume Up first):

```sh
python3 ../wait-for-ready.py --timeout 120 --settle 2 --capture-timeout 180 \
    --log /run/pocketfed-libcamera/capture.log -- \
    python3 ./libcamera-session.py --output /run/pocketfed-libcamera/session \
        --warmup 4 --timeout 60
```

Optional direct DRM/KMS preview on the phone (viable format permitting), passed
through unchanged:

```sh
    python3 ./libcamera-session.py --output DIR --display            # any connector
    python3 ./libcamera-session.py --output DIR --display=DSI-1      # named connector
```

| Option | Meaning |
| --- | --- |
| `--output DIR` | Fresh private output directory (required). |
| `--camera ID` | libcamera camera id; defaults to the stable rear identity. |
| `--stream SPEC` | cam `--stream` value; default 1280x960 RGB888 still. |
| `--warmup N` | Discarded warm-up frames; final still is frame `N+1` (default 4). |
| `--keep N` | Completed frames kept on disk during the run (default 2). |
| `--timeout SEC` | Bound for the whole cam run (default 60). |
| `--display[=connector]` | Forward cam `--display`; omitted by default. |
| `--cam-entry` / `--power-state` | Override the sibling helpers. |

Only options present in the device's `cam --help` are forwarded; no cam option
is invented.

## Cancellation and cleanup

The gate starts this helper in its own session/group and kills that group on
Volume Down. The helper starts `cam` **without** a new session, so cam and its
IPA helpers stay in the helper's group and are reached by both the gate's group
cleanup and the helper's own `SIGINT`/`SIGTERM` handling (which sends `SIGINT`
to cam, then escalates within the owned group only). No process-name-wide kills.

## Outputs

- `final.jpg` - the useful settled JPEG; `final.ppm` - the source frame
- `cam.log` - cam stdout including `--metadata` (private, retained)
- `power-before.json` / `power-after.json`, `status`, `result.json` - private

## Tests

```sh
python3 test-libcamera-session.py
```

Twelve tests use stub `cam`/`power-state`/`magick` binaries and never touch a
camera, DRM, gate or hardware. They cover the prune bound and final-frame
selection, a bounded warm-up to JPEG happy path with exact cam argv, too-few
frames, bad geometry, strict-decode failure, pre-release failure aborting before
capture, post-release failure, real `SIGTERM` cancellation killing cam, the
`--display` passthrough forms, the documented-option allowlist, preflight, and
the root guard.

## Hardware validation (root)

After a fresh Volume Up (and with Volume Down available to cancel), confirm on
test-sargo: the release gate passes before and after; `cam` starts through
`cam-system-heap`; `final.jpg` decodes at the expected geometry; `cam.log`
carries per-frame metadata; tmpfs never holds more than a few frames; and no cam
or IPA process survives exit.
