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
- The compositor runs on `WLR_BACKENDS=drm` on a dedicated VT, so it appears on
  the phone screen rather than an inactive headless output.
- `sm.puri.phoc auto-maximize true` (set best-effort at session start) makes the
  single Megapixels toplevel the active, full-screen window.

## Session bus, activation, and privacy

The launcher re-executes itself under `dbus-run-session`, so Phoc, Megapixels,
the `gdbus` action calls and the optional feedback cues share one private
session bus. `XDG_RUNTIME_DIR`, config, cache, pictures and logs all live under
`--output` (mode `0700`); JPEGs, logs and `result.json` are private. Nothing
outside that directory or the private bus is modified.

## Usage

Run it as the command of the readiness gate (the gate must come first):

```sh
python3 ../wait-for-ready.py --timeout 120 --settle 2 \
    --log /var/tmp/pocketfed-camera-visible/capture.log -- \
    python3 ./visible-session.py \
        --output /var/tmp/pocketfed-camera-visible/session --preview-seconds 10
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
| `--verify-jpeg` | Decode the saved JPEG with ImageMagick before reporting success. |
| `--allow-existing-compositor` | Skip the phoc/phosh-in-use refusal. |

## Systemd unit

`pocketfed-camera-visible.service` is a template. Edit the two `Environment`
paths for the phone, then `systemctl start` it (do not enable it by default):

```ini
Environment=POCKETFED_CAMERA_VISIBLE_REPO=/path/to/pocketfed
Environment=POCKETFED_CAMERA_VISIBLE_WORKDIR=/var/tmp/pocketfed-camera-visible
TTYPath=/dev/tty3
StandardInput=tty
Environment=WLR_BACKENDS=drm
Environment=WLR_RENDERER=gles2
Environment=LIBSEAT_BACKEND=noop
```

It conflicts with `getty@tty3.service` and is not part of any graphical target.
Remove `${WORKDIR}/session` between runs (the launcher requires a fresh output).

**Seat/DRM uncertainty to validate on hardware.** The template runs Phoc as root
on a dedicated VT with `LIBSEAT_BACKEND=noop`, which lets the process open DRM
and input directly without a logind session. This is the smallest credible
standalone path, but it can only be confirmed on the device. If Phoc cannot take
the DRM seat that way, use the image's existing greetd path instead: a trial
config with `[initial_session]` (the phrog config already shows this pattern)
running the same `visible-session.py` command as an unprivileged user. The
launcher is independent of which seat mechanism starts it. Check the result with:

```sh
systemctl status pocketfed-camera-visible
tail -f /var/tmp/pocketfed-camera-visible/capture.log
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

The tests use stub phoc/app/gdbus tools in a temporary directory. They cover
exactly one capture and quit on the happy path, control commands running before
capture, capture timeout cleanup, Phoc failing before the socket, SIGTERM during
preview cancelling and stopping owned children, `--check`/preflight behavior,
and that the systemd unit runs the gate before the session. No DRM device,
compositor, camera, session bus, SSH or network is touched.

## Remaining hardware validation

This is only the session half of the trial. On the device, confirm: Phoc takes
the DRM seat and the screen shows an active Megapixels preview; the window is
focused so AE/AF settle; a JPEG is saved and (with `--verify-jpeg`) decodes; the
gate's Volume Down cancels the running session; and all owned processes are gone
after exit.
