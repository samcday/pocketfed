# Visible Megapixels trial session

A minimal way to get a **real, active Megapixels preview on the test-sargo
display** for auto-exposure and manual focus, then take one explicit capture.
It never starts the camera before a fresh Volume Up readiness gesture.

This directory is new and self-contained. It complements, and does not modify,
the existing harness (`run-megapixels.py`, `run-libcamera.py`, `power-state.py`)
or the readiness gate in the parent directory.

## Flow

```text
systemd unit
  └─ wait-for-ready.py            # frozen gate (PR #66)
        ├─ fresh Volume Up press+release authorizes one command
        └─ visible-session.py     # the single authorized command
              ├─ start Phoc on the DRM display (dedicated VT)
              ├─ start Megapixels and wait for its session-bus name
              ├─ focus cue, preview settling interval (manual focus/exposure here)
              ├─ optional control commands
              ├─ capture action (exactly once), wait for a completed JPEG
              └─ quit, stop Phoc, clean up
```

The gate owns the session process group, so **Volume Down cancels** during the
countdown, the preview, or the running capture, and stops only that group.

## Why Phoc

- `phoc` 0.56 is installed in the device image (pulled in by phosh); cage is
  not. `man phoc` states it "works perfectly fine on its own"; the `-S` shell
  flag is only for attaching a shell, which this session deliberately omits.
- The compositor runs on the phone screen (a dedicated VT), not a headless
  output.
- `WLR_BACKENDS=drm,libinput`: the `drm` backend alone omits libinput, so
  touch/keyboard and therefore focus would be unavailable. wlroots only creates
  the input backend when it is listed (verified from the installed
  `libwlroots`, which logs "Loading user-specified backends due to
  WLR_BACKENDS" and "Starting libinput backend").
- `sm.puri.phoc auto-maximize true` is set best-effort at session start so the
  single Megapixels toplevel is full-screen.
- **Focus honesty.** A maximized toplevel is not proof of
  `gtk_window_is_active`. With libinput present the single maximized window is
  normally focused, but this tool cannot guarantee the app's active state. If
  the preview stays blank, the operator/root must activate it (an existing
  pointer toolkit or a tap); the launcher does not fake that guarantee.

## Session bus, activation, and privacy

The launcher re-executes itself under `dbus-run-session`, so Phoc, Megapixels,
the `gdbus` action calls and the optional feedback cues share one private
session bus. `XDG_RUNTIME_DIR`, config, cache, pictures and logs all live under
`--output` (mode `0700`); JPEGs, logs and `result.json` are private. Nothing
outside that directory or the private bus is modified.

## Usage

Run it as the command of the readiness gate (the gate must come first):

```sh
python3 ../wait-for-ready.py --timeout 120 --settle 2 --capture-timeout 180 \
    --log /run/pocketfed-camera-visible/capture.log -- \
    python3 ./visible-session.py \
        --output /run/pocketfed-camera-visible/session --preview-seconds 10
```

Check the resolved plan and tools without starting a session:

```sh
python3 ./visible-session.py --output /var/tmp/vs-check --check
```

Options of interest:

| Option | Meaning |
| --- | --- |
| `--output DIR` | Fresh private directory for all session output. |
| `--preview-seconds N` | Visible settling/manual-focus window (0..300, default 10). |
| `--capture-timeout N` | Bound for the capture action and JPEG wait (1..600). |
| `--control-command CMD` | Shell command after settling, before capture; repeatable. |
| `--focus-cue` / `--capture-cue` | Existing-UI cues (default the `fbcli` events below; empty disables). |
| `--allow-existing-compositor` | Skip the phoc/phosh-in-use refusal. |

Capture completion is not a non-empty file. Like `run-megapixels.py`, the
launcher requires the Megapixels postprocessor's ExifTool `Software` tag, a
3-second stable file, a full pixel decode with ImageMagick, and readable
dimensions, which are recorded in `result.json`. `exiftool` and `magick` are
required tools (checked by `--check`).

## Systemd unit

`pocketfed-camera-visible.service` is a template. Edit the repository
`Environment` path for the phone, then `systemctl start` it. It has no
`[Install]` section: this trial is armed manually and must not start at boot.

```ini
Environment=POCKETFED_CAMERA_VISIBLE_REPO=/path/to/pocketfed
Environment=POCKETFED_CAMERA_VISIBLE_WORKDIR=/run/pocketfed-camera-visible
RuntimeDirectory=pocketfed-camera-visible
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
TTYPath=/dev/tty3
StandardInput=tty
Environment=WLR_BACKENDS=drm,libinput
Environment=WLR_RENDERER=gles2
Environment=LIBSEAT_BACKEND=noop
KillMode=control-group
```

`RuntimeDirectory` creates the private work directory (and so the gate's
`capture.log` parent) before `ExecStart`. It survives service exit for photo
retrieval and is discarded on reboot. Use a fresh output directory for each trial.
`KillMode=control-group` keeps every descendant in the unit cgroup, so even a
helper that creates its own session is cleaned up when the service stops or is
cancelled. The gate bound is explicit: `--capture-timeout 180` covers startup
(20s) + preview (10s) + control (15s) + capture/JPEG (60s) with margin. Remove
`${WORKDIR}/session` between runs (the launcher requires a fresh output).

**Seat/DRM uncertainty to validate on hardware.** The template runs Phoc as root
on a dedicated VT with `LIBSEAT_BACKEND=noop`, which lets the process open DRM
and input directly without a logind session. This is the smallest credible
standalone path, but it can only be confirmed on the device. If Phoc cannot take
the DRM seat that way, use the image's existing greetd path instead: a trial
config with `[initial_session]` (the phrog config already shows this pattern)
running the same visible session command as an unprivileged user. The launcher
is independent of which seat mechanism starts it. Check the result with:

```sh
systemctl status pocketfed-camera-visible
tail -f /run/pocketfed-camera-visible/capture.log
```

## Manual focus and exposure

During `--preview-seconds` the operator adjusts Megapixels on the visible UI.
For scripted control, use `--control-command` with the exact actions verified on
the device; this project does not guess Megapixels action names. The readiness
gate already uses the verified `capture`, `quit` and `switch-camera` actions.

## Operator cues

- **Screen**: the active Megapixels preview itself, and the blank-to-preview
  transition when Phoc starts, are the primary cues.
- **Haptics/audio**: the defaults run `fbcli -E camera-focus` before the preview
  and `fbcli -E camera-shutter` at capture. These are existing feedbackd events
  from `/usr/share/feedbackd/themes/default.json`. They are best-effort: if
  feedbackd is not available on the session bus the cue is skipped, not fatal.

## Tests

```sh
python3 test-visible-session.py
```

The tests use stub phoc/app/gdbus/exiftool/magick tools in a temporary
directory. They cover exactly one capture and quit on the happy path with
recorded dimensions, control commands running before capture, capture timeout
cleanup, Phoc failing before the socket, SIGTERM during preview cancelling and
stopping owned children, a lingering same-group helper surviving its leader and
still being reaped, `--check`/preflight behavior, and that the systemd unit runs
the gate before the session, creates the work directory, includes libinput,
bounds the gate, and has no `[Install]`. One test runs the real installed
`gdbus wait` under `dbus-run-session` to prove the integer `--timeout` token is
accepted (a float token makes `gdbus` print usage and abort before the app is
queried). No DRM device, compositor, camera, session bus, SSH or network is
touched by the other tests.

## Remaining hardware validation

This is only the session half of the trial. On the device, confirm: Phoc takes
the DRM seat and the screen shows an active Megapixels preview; libinput is
present and the window is focused so AE/AF settle (activate it manually if not);
a JPEG is saved, passes the ExifTool/decode/dimension checks, and is recorded; the
gate's Volume Down cancels the running session; and all owned processes,
including any descendant, are gone after exit.
