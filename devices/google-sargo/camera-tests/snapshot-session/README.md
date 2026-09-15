# GNOME Snapshot capture session

A minimal way to drive the **GNOME Snapshot** camera app on the test-sargo
display without any touch interaction: the launcher publishes the camera
through PipeWire/WirePlumber, starts Snapshot on a standalone Phoc compositor,
injects the shutter accelerator (`t`) with `wtype`, and keeps pressing until a
JPEG lands in Snapshot's `Pictures/Camera` directory. It is the post-readiness
half of a trial: `wait-for-ready.py` first requires a fresh Volume Up
press/release (and keeps monitoring Volume Down), then runs this helper as its
single command.

This directory is self-contained. It reuses the sibling
[`libcamera-session`](../libcamera-session/README.md) helper's reviewed
`Reporter`, release-gate, ImageMagick-identify and scoped process-cleanup
functions; it does not copy that framework. Facts about Snapshot 51.beta,
PipeWire 1.6.8, WirePlumber 0.5.14 and phoc 0.57 are cited in the research
report `out/camera-snapshot-research-20260915/report.md`.

## Flow

```text
systemd unit (dedicated VT)
  └─ wait-for-ready.py                  # fresh Volume Up authorizes; Volume Down cancels
        └─ snapshot-session.py          # the single authorized command
              ├─ power-state.py --require-released              (before; no camera start)
              ├─ Phoc standalone on the DRM seat (private runtime dir/socket)
              ├─ PipeWire, then WirePlumber (libcamera monitor publishes the node)
              ├─ wait for pw-dump Video/Source node
              │     node.name startswith libcamera_input._base_soc_0_cci_ac4a000_i2c-bus_0_camera_1a
              ├─ snapshot under dbus-run-session (private HOME/XDG, GSettings memory)
              ├─ wtype t, retried until $HOME/Pictures/Camera/*.jpeg is size-stable
              ├─ copy newest JPEG to <out>/photo.jpeg (0600), measure geometry
              │     magick identify when available, else pure-Python SOI/EOI/SOF
              ├─ teardown snapshot, WirePlumber, PipeWire, Phoc (reverse order)
              ├─ power-state.py --require-released              (after; always once pipeline started)
              └─ result.json (private)
```

The camera is never started before the gate authorizes the run. Within the
helper, the strict release gate runs before Phoc or the PipeWire pipeline
start, and Snapshot is only launched after the camera node is visible in
`pw-dump`. Reconciliation point: the after release gate is armed as soon as
the PipeWire pipeline starts (WirePlumber's libcamera monitor is what touches
the devices), so a failure before Snapshot still verifies release.

## Prerequisites

- **GNOME Snapshot** (`snapshot`, Fedora 46 `51~beta`).
- **PipeWire** (`pipewire`) and **WirePlumber** (`wireplumber`).
- **`pipewire-gstreamer`** — the PipeWire GStreamer plugin, which provides the
  `pipewiredeviceprovider` Snapshot enumerates with. It is not listed in the
  Snapshot spec but is mandatory at runtime.
- **`pipewire-plugin-libcamera`** — the SPA libcamera plugin WirePlumber's
  `monitor.libcamera` loads to publish the `Video/Source` node.
- **GStreamer plugins:** `gstreamer1-plugins-bad-free` (`camerabin`),
  `gstreamer1-plugin-gtk4`, and `gstreamer1-plugins-good` (`jpegenc`).
- **Phoc** (standalone compositor, pulled in by phosh), started without
  `-S/--shell` so input is allowed.
- **`wtype`** — virtual keyboard over `zwp_virtual_keyboard_v1`, which phoc
  0.57 implements.
- **Root**, for the DRM seat and the release gate.
- **`magick`** (ImageMagick) is optional; without it the launcher validates the
  JPEG and reads geometry with a built-in SOI/EOI/SOF parser.

## Usage

Run it as the command of the readiness gate (the gate must come first):

```sh
python3 ../wait-for-ready.py --timeout 180 --settle 2 --capture-timeout 300 \
    --log /run/pocketfed-camera-snapshot/capture.log -- \
    python3 ./snapshot-session.py \
        --output /run/pocketfed-camera-snapshot/session \
        --settle 8 --shutter-retries 5 --retry-interval 3 --timeout 180
```

| Option | Meaning |
| --- | --- |
| `--output DIR` | Fresh private directory (required); runtime, HOME and logs live here. |
| `--camera-node PREFIX` | `node.name` prefix to wait for (default: stable rear libcamera node). |
| `--softisp-mode {gpu,cpu}` | `LIBCAMERA_SOFTISP_MODE` for the pipeline (default `gpu`). |
| `--libcamera-log LEVELS` | Optional `LIBCAMERA_LOG_LEVELS` value. |
| `--settle SEC` | Delay before the first shutter press, 0..120 (default 8). |
| `--shutter-retries N` | Shutter presses before giving up, 1..60 (default 5). |
| `--retry-interval SEC` | Seconds between presses/polls, 1..60 (default 3). |
| `--startup-timeout SEC` | Bound for the Phoc socket, 1..120 (default 20). |
| `--node-timeout SEC` | Bound for the camera node, 1..300 (default 30). |
| `--timeout SEC` | Bound for the whole run (before teardown), 1..600 (default 180). |
| `--socket NAME` | Private Wayland socket name under the runtime dir. |
| `--phoc` / `--pipewire` / `--wireplumber` / `--snapshot` / `--wtype` / `--pw-dump` / `--power-state` / `--magick` | Override tools. A bare name is resolved on `PATH`; an explicit path must be a file. |
| `--allow-existing-compositor` | Skip the phoc/phosh-in-use refusal. |

`dbus-run-session` is used to give Snapshot a private session bus when it is on
`PATH`; otherwise the launcher runs Snapshot with no bus, which is supported
because Snapshot falls back to the direct PipeWire provider.

## Result and release

`result.json` records `status`, `camera_node`/`camera_node_id`/`camera_node_name`,
`softisp_mode`, every timeout, `shutter_presses`, `source_jpeg`, `photo`,
`geometry`/`width`/`height`/`geometry_method`, `camera_attempted`,
`camera_released`, `release_error`, `dbus_run_session`, the per-tool return
codes (`phoc`, `pipewire`, `wireplumber`, `snapshot`, `wtype`, `pw_dump`,
`magick`), `remaining_processes` and `error`.

A run exits `0` only when a decoded-geometry JPEG exists **and** the after
release gate passed and no owned process survived cleanup. A cancelled run
returns `130` for `SIGINT` (the gate's first signal) and `143` for `SIGTERM`.

## Cancellation and cleanup

The gate starts this helper in its own session/process group. Phoc, PipeWire,
WirePlumber and Snapshot are started **without** a new session, so they stay in
that group: a Volume Down reaches the helper's `SIGINT`/`SIGTERM` handler,
which records the signal, blocks repeats, tears the children down in reverse
start order, runs the after release gate and writes `result.json`. Cleanup uses
the sibling helper's scoped `terminate_process_tree`; no process-name-wide
kills. Surviving owned processes are recorded and make the run fail.

## Choices and limitations

- **Camera-node prefix, not camera index.** WirePlumber names the node from the
  libcamera id, so the default prefix pins the stable rear sensor rather than a
  rebuild-sensitive index.
- **Polling `pw-dump` JSON.** No `grep` over human output; a non-zero or
  unparsable `pw-dump` is retried until `--node-timeout`.
- **Shutter is best-effort.** Snapshot's API has no shortcut to switch or
  otherwise control the camera; the accelerator `t` is the only trigger, and
  the retry loop tolerates a slow first map/focus. Whether the saved frame is
  focused, correctly oriented and useful is a separate hardware/operator
  decision; no EXIF orientation is written by this version.
- **Not validated natively.** The launcher has only been exercised with
  host-side stub tools; the physical run on the test phone is pending.

## Systemd unit example

`pocketfed-camera-snapshot.service` is a template for a manually armed trial on
a dedicated VT. It has no `[Install]` section and is not pulled in by any
target, so it cannot start at boot. Edit the repository path, then start it
explicitly:

```sh
systemctl daemon-reload
systemctl start pocketfed-camera-snapshot.service
journalctl -u pocketfed-camera-snapshot -f
```

```ini
[Unit]
Description=PocketFed Sargo Snapshot camera trial (Volume-Up gate + PipeWire + Snapshot)
Conflicts=getty@tty3.service
After=systemd-user-sessions.service

[Service]
Type=simple
Environment=POCKETFED_CAMERA_SNAPSHOT_REPO=/path/to/pocketfed
Environment=POCKETFED_CAMERA_SNAPSHOT_WORKDIR=/run/pocketfed-camera-snapshot
RuntimeDirectory=pocketfed-camera-snapshot
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes

# Standalone DRM session on a dedicated VT. libinput must be listed explicitly.
Environment=WLR_BACKENDS=drm,libinput
Environment=WLR_RENDERER=gles2
Environment=LIBSEAT_BACKEND=noop
TTYPath=/dev/tty3
StandardInput=tty
TTYReset=yes
TTYVHangup=yes

# Contain every descendant in the unit cgroup, including any helper that created
# its own session and would escape process-group cleanup on cancellation.
KillMode=control-group
TimeoutStopSec=30

# The gate bound must cover Phoc/Node start-up, the settle/shutter window and
# both release gates with margin.
ExecStart=/usr/bin/python3 ${POCKETFED_CAMERA_SNAPSHOT_REPO}/devices/google-sargo/camera-tests/wait-for-ready.py \
    --timeout 180 --settle 2 --capture-timeout 300 \
    --log ${POCKETFED_CAMERA_SNAPSHOT_WORKDIR}/capture.log \
    -- /usr/bin/python3 ${POCKETFED_CAMERA_SNAPSHOT_REPO}/devices/google-sargo/camera-tests/snapshot-session/snapshot-session.py \
    --output ${POCKETFED_CAMERA_SNAPSHOT_WORKDIR}/session \
    --settle 8 --shutter-retries 5 --retry-interval 3 \
    --startup-timeout 20 --node-timeout 30 --timeout 180
```

Use a fresh work directory for each run and preserve its JPEG and logs privately.

## Tests

```sh
python3 test-snapshot-session.py
```

The tests use stub `phoc`/`pipewire`/`wireplumber`/`pw-dump`/`snapshot`/
`wtype`/`power-state`/`magick`/`dbus-run-session` tools in a temporary
directory and never touch DRM, a compositor, a camera, a gate or hardware. They
cover a real subprocess happy path (AF_UNIX listening socket, JSON node match,
two shutter presses until a size-stable JPEG, ImageMagick geometry); the
pure-Python JPEG fallback; a camera node that never appears; exhausting the
shutter retries with no JPEG; a failing after release gate; `SIGTERM`
cancellation that still tears down and runs the after gate; and option
validation. They are process/behaviour regressions, not mirrors of the code.
