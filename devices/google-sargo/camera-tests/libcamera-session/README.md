# libcamera-only capture session

Runs one bounded `cam` session through the existing private-system-heap wrapper
and produces a **final-frame JPEG** plus retained `cam --metadata`. No desktop,
no Megapixels, no compositor. It depends only on the sibling
`../cam-system-heap` and `../power-state.py`; it does not use `visible-session/`
or `native-bootstrap/`.

## Source-verified contract (libcamera 0.7.2, `src/apps/cam`)

- `camera_session.cpp` rejects `--display` together with `--file` (and requires a
  single *viewfinder* stream for `--display`). A file-producing run therefore
  cannot show preview; on-screen UI acceptance stays **pending**. `--display` is
  not offered here.
- `file_sink.cpp` expands the first `#` in `--file` to
  `<streamName>-<sequence>`, and `camera_session.cpp` builds `streamName` as
  `cam<idx>-stream<idx>` (e.g. `frame-cam0-stream0-000123.ppm`). A numbered
  pattern is not `frame-<digits>`.
- `PPMWriter` opens the file with `std::ofstream(filename, std::ios::binary)`,
  which truncates. A **fixed `.ppm` name** is overwritten by every frame and
  holds the final frame after the run, so no warm-up pruning is needed.
- `camera_session.cpp` prints one `... <stream> seq: <digits> bytesused: ...`
  line per completed request and, with `--metadata`, tab-indented control lines.
  The completed-frame count is verified from those `seq:` lines.
- `--script` is a YAML capture-session config (`capture_script.cpp`), not Python
  and not dependent on `python3-libcamera`; it is a possible future lever for
  per-frame controls, not used here.

## Flow

```text
wait-for-ready.py                 # fresh Volume Up authorizes; Volume Down cancels
  └─ libcamera-session.py
        ├─ power-state.py --require-released            (before)
        ├─ cam-system-heap -c REAR --stream role=still,width=1280,height=960,pixelformat=RGB888 \
        │                  --capture=<warmup+1> --metadata --file=<out>/frame.ppm
        ├─ verify completed frames from cam.log `seq:` lines (>= warmup+1)
        ├─ decode frame.ppm, convert to final.jpg, strictly decode JPEG, check geometry
        ├─ power-state.py --require-released            (after, always once cam was attempted)
        └─ result.json (private)
```

## Release, failure and cancellation

- The after release gate runs in `finally` whenever the camera launch was
  attempted, including cam timeout, capture error, decode/conversion failure and
  cancellation. The original cause is kept in `result.json:error`; a failed
  release is recorded separately as `camera_released: false` and
  `release_error`. A run is never reported as `passed` unless the after release
  is confirmed, so the helper cannot return 0 without a decode-verified JPEG.
- `frames_captured` is the number of completed-request lines, never derived from
  the maximum sequence (sequences can start above zero or contain gaps);
  `sequence_min`/`sequence_max` are recorded only as observations.
- Repeated cancellation cannot skip cleanup: on the first `SIGINT`/`SIGTERM`
  the runner records the signal, then blocks further `SIGTERM`/`SIGINT` while it
  stops cam and runs the after release gate and result write.

## Warm-up honesty

`--warmup` (default **90**) is the number of captured warm-up frames; one final
frame follows, so `--capture=<warmup+1>`. This is an initial calibration sample,
not proof of AE/AF convergence. The JPEG is reported as the **final captured
frame**, not as settled or useful; that can only be established on hardware
(the phone UI/quality acceptance remains pending).

## Usage

```sh
python3 ../wait-for-ready.py --timeout 120 --settle 2 --capture-timeout 180 \
    --log /run/pocketfed-libcamera/capture.log -- \
    python3 ./libcamera-session.py --output /run/pocketfed-libcamera/session \
        --warmup 90 --timeout 60
```

| Option | Meaning |
| --- | --- |
| `--output DIR` | Fresh private output directory (required). |
| `--camera ID` | libcamera camera id; defaults to the stable rear identity. |
| `--stream SPEC` | cam `--stream` value; default 1280x960 RGB888 still. |
| `--warmup N` | Warm-up frames before the final frame (default 90, 1..2000). |
| `--timeout SEC` | Bound for the whole cam run (default 60, 1..300). |
| `--cam-entry` / `--power-state` / `--magick` | Override the helpers/tool. |

Only `-c`, `--stream`, `--capture`, `--file`, `--metadata` are forwarded, all
present in the device's `cam --help`; no option is invented.

## Cancellation and cleanup

The gate starts the helper in its own session/group and kills that group on
Volume Down. The helper starts `cam` **without** a new session, so cam and its
IPA helpers stay in that group; its own `SIGINT`/`SIGTERM` handling sends
`SIGINT` and then escalates within the owned group only (group members when it
is the leader, otherwise cam plus its live descendants). Reaped processes are
never reported as survivors. No process-name-wide kills.

## Outputs (all private, mode 0600)

`frame.ppm` (fixed final frame), `final.jpg`, `cam.log` (`--metadata` retained),
`power-before.json`, `power-after.json`, `status`, `result.json`
(`frames_captured`, `sequence_min`, `sequence_max`, `camera_attempted`,
`camera_released`, `release_error`, `jpeg`, `geometry`, `error`).

## Tests

```sh
python3 test-libcamera-session.py
```

Seventeen tests use stub `cam`/`power-state`/`magick` tools and never touch a
camera, DRM, gate or hardware. They cover the source-derived contracts (fixed
`.ppm` with no `#`, the `cam<idx>-stream<idx>-<seq>` expansion that breaks
`frame-<digits>` matching, the `seq:` log parser including gaps and non-zero
starts, and that `--display` is not offered), a bounded warm-up happy path with
frame-count verification, a frame-count shortfall, decode/geometry failures,
pre/post release failures, the after release gate running and recording its
failure after cam timeout and after decode failure, real `SIGTERM` and repeated
`SIGTERM` cancellation killing cam without skipping release, preflight, and the
root guard.

## Hardware validation (root)

After a fresh Volume Up (Volume Down cancels), confirm: release gate passes
before and after; `cam` starts via `cam-system-heap`; `cam.log` reports at least
`warmup+1` completed frames; `frame.ppm`/`final.jpg` decode at the expected
geometry; `cam.log` carries per-frame metadata; and no cam or IPA process
survives exit. Whether the final frame is visually useful is a separate hardware
decision.
