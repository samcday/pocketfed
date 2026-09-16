# Visible qcam capture session

A minimal, libcamera-only way to show the **patched qcam** viewfinder on the
test-sargo display and have it save exactly one JPEG automatically, without a
Megapixels dependency or any touch interaction. It is the post-readiness half
of a trial: `wait-for-ready.py` first requires a fresh Volume Up press/release
(and keeps monitoring Volume Down), then runs this helper as its single command.

This directory is self-contained. It reuses the sibling
[`libcamera-session`](../libcamera-session/README.md) helper's reviewed
`Reporter`, release-gate, JPEG-decode/identify and scoped process-cleanup
functions; it does not copy that framework. It reuses only the generic
standalone-compositor start-up from the archived Megapixels trial; none of that
trial's application, session-bus, gdbus, cue or capture code is used.

## Flow

```text
systemd unit (dedicated VT)
  └─ wait-for-ready.py            # fresh Volume Up authorizes; Volume Down cancels
        └─ qcam-session.py        # the single authorized command
              ├─ power-state.py --require-released              (before; no camera start)
              ├─ Phoc standalone on the DRM seat (private runtime dir/socket)
              ├─ cam-system-heap --tool qcam -c REAR -r qt \
              │     --stream role=viewfinder,width=1280,height=960,pixelformat=RGB888 \
              │     --output <out>/frame.jpg --after-frames <N>
              ├─ qcam renders the viewfinder, saves one JPEG after N frames, exits 0
              ├─ full ImageMagick decode, geometry check (JPEG <w> <h>)
              ├─ power-state.py --require-released              (after; always once attempted)
              └─ result.json (private)
```

The camera is not started before the gate authorizes the run. Within the
helper, the strict release gate runs before Phoc or qcam start, and the camera
is only launched after Phoc's Wayland socket appears as a listening Unix socket
and the JPEG path is fixed.

## Prerequisites

- **Patched qcam.** `packages/libcamera/patches/0002-qcam-bounded-save.patch`
  adds `--output`/`--after-frames` and is included in the installed native.2
  candidate. A stock `qcam` rejects those options and this helper fails closed
  with no JPEG.
- **Qt runtime plugins on the device:** the Qt Wayland platform plugin (for
  `QT_QPA_PLATFORM=wayland`) and the Qt JPEG image plugin (`libqjpeg`, from
  `qt6-qtbase-gui`) for `.jpg` output.
- **Phoc** installed (pulled in by phosh); `cage` is not in the image.
- **Root**, for the private DMA-heap mount namespace and the release gate.
- `magick` (ImageMagick) on `PATH`.

Phoc's `--socket` and `--no-xwayland` options are source-verified from the
installed Phoc (`src/main.c` option table) and `man phoc`; Phoc creates the
compositor socket with `wl_display_add_socket` under `XDG_RUNTIME_DIR`. Root
should still confirm the device build's `phoc --help` natively.

## Usage

Run it as the command of the readiness gate (the gate must come first):

```sh
python3 ../wait-for-ready.py --timeout 120 --settle 2 --capture-timeout 180 \
    --log /run/pocketfed-camera-qcam/capture.log -- \
    python3 ./qcam-session.py \
        --output /run/pocketfed-camera-qcam/session \
        --startup-timeout 20 --timeout 90 --after-frames 300
```

| Option | Meaning |
| --- | --- |
| `--output DIR` | Fresh private directory (required); output and runtime live here. |
| `--camera ID` | libcamera camera id; defaults to the stable rear identity. |
| `--stream SPEC` | qcam `--stream` value; default viewfinder 1280x960 RGB888. |
| `--after-frames N` | Rendered viewfinder frames before one save, 1..1800 (default 300, roughly 10 s at 30 fps). |
| `--timeout SEC` | Bound for the whole qcam run, 1..300 (default 90). |
| `--startup-timeout SEC` | Bound for the Phoc socket, 1..120 (default 20). |
| `--socket NAME` | Private Wayland socket name under the runtime dir. |
| `--phoc` / `--cam-entry` / `--power-state` / `--magick` | Override the helpers/tools. A bare name is resolved on `PATH`; an explicit path must be a file. |
| `--allow-existing-compositor` | Skip the phoc/phosh-in-use refusal. |

`--after-frames` is a calibration parameter, not proof that AE/AF have settled;
a small value can save an unsettled frame, and `1800` is only qcam's hard cap.
The caller still enforces the wall-clock bound through `--timeout` (and the
gate's `--capture-timeout`).

## Result and release

`result.json` records `status`, `camera`, `stream`, `after_frames`, `jpeg`,
`geometry`, `camera_attempted`, `camera_released`, `release_error`, the qcam
`timed_out`/`returncode`, the Phoc exit code, `remaining_processes` and `error`.

- The after release gate runs in `finally` whenever the camera launch was
  attempted, including qcam timeout, missing/invalid JPEG, decode/geometry
  failure and cancellation. A run is never reported as `passed` unless the
  after release is confirmed, so the helper cannot return 0 without a
  decode-verified JPEG and a released camera.
- A cancelled run returns `130` for `SIGINT` and `143` for `SIGTERM`.

## Cancellation and cleanup

The gate starts this helper in its own session/process group. Phoc and qcam are
started **without** a new session, so they stay in that group: a Volume Down
during the preview or the running qcam reaches them directly, and the helper's
own `SIGINT`/`SIGTERM` handler re-runs cleanup after blocking further signals.
Cleanup uses the sibling helper's scoped `terminate_process_tree` (the owned
group when this helper is the leader, otherwise the process plus its live
descendants); no process-name-wide kills. Surviving owned processes are
recorded and make the run fail.

The launcher deliberately does **not** create a private session bus or use
`gdbus`, so the archived trial's gdbus integer-timeout pitfall does not apply
here. Phoc is the only compositor and is stopped on every exit path.

Window sizing is **not** managed: the launcher no longer runs a best-effort
`gsettings set sm.puri.phoc auto-maximize true`, because without a private
session bus/dconf that cannot be claimed to work. qcam's saved frame is the
full viewfinder stream resolution regardless of window size, but the visible
preview may be a non-maximized window. Maximizing the preview is a pending UI
step to source-verify (for example a contained session mechanism) and validate
natively; it is not applied here.

## Systemd unit

`pocketfed-camera-qcam.service` is a template for a manually armed trial on a
dedicated VT. Edit the repository path, then start it explicitly:

```sh
systemctl daemon-reload
systemctl start pocketfed-camera-qcam.service
journalctl -u pocketfed-camera-qcam -f
```

It has no `[Install]` section and is not pulled in by any target, so it cannot
start at boot. `RuntimeDirectory` creates the private work directory before
`ExecStart`; `KillMode=control-group` contains every descendant (including a
helper that created its own session) when the service stops. Use a fresh work
directory for each run and preserve its images and logs privately.

## Tests

```sh
python3 test-qcam-session.py
```

The tests use stub `phoc`/`qcam`/`power-state`/`magick` tools in a temporary
directory and never touch DRM, a compositor, a camera, a gate or hardware. They
cover a real subprocess happy path that resolves bare `phoc`/`magick` on `PATH`
and requires a real AF_UNIX listening socket; `SIGTERM` cancellation killing the
owned Phoc and qcam processes without skipping the after release gate; a qcam
run that exits 0 without saving a JPEG; an after-release failure; a reported
cleanup survivor failing the run even when release succeeded; a tool timeout
recorded as a failure with no traceback; and a Phoc start-up that never creates
its socket being killed and failing closed. They are process/behaviour
regressions, not mirrors of the code.

## Native validation

On the fresh `sargo-camera-camcc-02-20260914` boot, a separate 15-second
compositor-only preflight using this environment opened Phoc's Wayland display
and the `DSI-1` panel. The trial then stopped at its explicit time limit. The
strict camera release check still passed afterward; no camera client ran.
Phoc warned about missing panel metadata and a session-bus screensaver proxy.
This validates compositor startup, not qcam preview or saving.

The patched qcam must be compiled and installed on the phone first. After a
fresh Volume Up (Volume Down cancels), confirm: the release gate passes before
and after; Phoc takes the DRM seat on the dedicated VT; the qcam viewfinder is
visible; qcam exits 0 after saving one JPEG; the JPEG fully decodes at
1280x960; and no Phoc or qcam process survives exit. Whether the saved frame is
visually useful, focused and correctly oriented is a separate hardware and
operator decision; this helper proves mechanism and release only.

Remaining native checks:

- Patch 0002 compiled in `4.fc46.native.2` and is installed on the test phone;
  14 isolated help/invalid-option cases passed. The actual gated preview/save
  remains pending. A stock `qcam` still rejects the added options.
- The Qt Wayland platform plugin and the Qt JPEG plugin must be present; a
  missing plugin fails qcam start-up or the save, never silently.
- Standalone root Phoc (`LIBSEAT_BACKEND=noop`, `WLR_BACKENDS=drm,libinput`)
  reached the panel in the preflight; the complete launcher still needs a
  physical readiness-gated capture.
- This launcher does not create a private D-Bus session or use gdbus. If Phoc
  needs a session bus on the device, that must be added and validated rather
  than assumed.
- Preview window sizing/maximisation is not applied (see above).
- `--after-frames` is a calibration count; the wall-clock bound is the
  launcher's `--timeout` plus the gate's `--capture-timeout`.
