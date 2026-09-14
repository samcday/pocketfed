# Camera readiness gate

`wait-for-ready.py` is a small, self-contained gate for the Sargo camera trial.
The phone starts face-down, so no test may capture until the operator has picked
it up, aimed the rear camera, and explicitly signaled readiness with a hardware
button. Readiness is **never** inferred from elapsed time.

After the operator gives a fresh **Volume Up press+release**, the gate waits a
short settling/countdown interval so there is time to hold still, then
authorizes exactly one capture command. **Volume Down** cancels at any point,
including during the countdown and while the capture is running. Repeats and
keys already held when the gate starts cannot authorize a capture.

This file documents the tool; it does not modify the existing trial harness
(`README.md`, `run-megapixels.py`, `run-libcamera.py`, `power-state.py`).

## What it does and does not do

- Discovers capable input devices through the Linux evdev API only:
  `EVIOCGBIT` for the key bitmap, `EVIOCGKEY` for keys already down, and
  `EVIOCGNAME` for a label.
- Never reads or writes arbitrary GPIO and never accesses
  `/sys/kernel/debug/gpio` (a broad debug read there previously coincided with
  a kernel lockup on the `.8` kernel).
- Keeps monitoring the same input devices while the authorized capture runs, so
  a Volume Down or an input disconnect stops only the capture process group this
  tool started.
- Fails closed on incomplete input state: a device whose `EVIOCGKEY` cannot be
  read is excluded, and a failed resync after `SYN_DROPPED` cancels rather than
  assuming no key is held.
- Does not itself assess image quality, focus, exposure, or camera power
  release. It only gates a single capture; keep using the existing checker and
  `power-state.py` for the rest of the acceptance.
- Keeps output and any status/capture files private by default: the status file
  is created mode `0600` via an atomic replace, capture logs are created `0600`,
  and instruction text is length-bounded.

## Requirement sources

- The user designated `test-sargo` for liveboot camera iteration and specified
  that every camera test must wait for them to pick the phone up, aim, and press
  a volume button.
- Root executive owns hardware. This tool performs no USB/UART/SSH access, no
  boot/flash, and no capture by itself.

## Usage

Run on the disposable liveboot session (serial console or the app user's
terminal). Point it at the real input directory for an actual trial; the
examples below use the defaults.

```sh
# Wait for Volume Up, then run one libcamera capture:
python3 wait-for-ready.py --timeout 120 --settle 4 -- \
    cam -c /base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a \
    --stream role=still,width=1280,height=960,pixelformat=RGB888 \
    --capture=1 --file=/var/tmp/pocketfed-camera-raw/ready-#.ppm

# Wait and only report readiness, without running anything (a wrapper reacts):
python3 wait-for-ready.py --timeout 120 --settle 4 --quiet
```

Options:

| Option | Meaning |
| --- | --- |
| `--dev-root DIR` | Directory containing `event*` nodes (default `/dev/input`). |
| `--timeout SEC` | Max wait for a fresh Volume Up, 1..3600 (default 120). |
| `--settle SEC` | Hold-still countdown after authorization, 0..60 (default 3). |
| `--capture-timeout SEC` | Max run time for the single command, 1..600 (default 30). |
| `--grab` | Attempt `EVIOCGRAB` on capable devices (default off). |
| `--status-file PATH` | Mirror the latest state line to a private `0600` file. |
| `--notify PROGRAM` | Best-effort existing-UI cue; called `PROGRAM STATE DETAIL`. |
| `--log PATH` | Private `0600` log for the capture command. |
| `--quiet` | Omit human instruction text from state lines. |
| `-- CMD ...` | The single capture command to run once authorized. |

## States and output contract

One line per transition is printed to stdout (and therefore the serial/log),
and mirrored to `--status-file`/`--notify` when configured:

```text
pocketfed-camera-readiness: state=<state> detail="<detail>" instruct="<text>"
```

| State | Meaning |
| --- | --- |
| `discovering` | Scanning evdev nodes for volume-key capability. |
| `waiting` | Armed; a fresh Volume Up press+release is required. |
| `settling` | Authorized gesture seen; countdown before capture. |
| `authorized` | Readiness confirmed (only from the button gesture). |
| `cancelled` | Volume Down, `SYN_DROPPED` or input loss; the owned capture was stopped. |
| `timeout` | No fresh Volume Up within `--timeout`; no capture run. |
| `capturing` | Running the single capture command; Volume Down still cancels. |
| `capture-failed` | The command timed out, failed, or left live processes. |
| `complete` | The single capture command finished. |

Exit status: `0` authorized (and any command succeeded), `2` cancelled,
`3` timed out, `4` capture command failed, `130` interrupted.

`detail` and `instruct` are whitespace-collapsed and truncated, so a log parser
can treat the line as bounded tokens. Every cancellation detail ends in
`before-capture` or `during-capture`, so the log states whether the command had
already started when the cancel arrived.

## Authorization state machine

A capture is authorized only by a **fresh** `KEY_VOLUMEUP` press (`value=1`)
followed by its release (`value=0`) from the **same device**. A press on one
node and a release on another never pair up, even if several nodes advertise
Volume Up.

- `KEY_VOLUMEDOWN` press cancels immediately.
- `value=2` (repeat) events are ignored and never authorize.
- Keys already down when the gate starts (`EVIOCGKEY`) are ignored until they
  are released, and their release does not authorize. A later fresh press is
  still required. This covers the case where a volume key is held during start.
- A capable device whose initial `EVIOCGKEY` fails has unknown state and is
  excluded from authorization; it is never treated as having no keys held.
- `SYN_DROPPED` invalidates any partial gesture and drops pending state. Per
  evdev semantics, that device's events are then ignored until the next
  `SYN_REPORT`, so a stale press/release from the lost interval cannot
  authorize. At the boundary the runner re-reads `EVIOCGKEY`; if that fails it
  fails closed (cancels) instead of assuming no key is held. A `SYN_DROPPED`
  during the countdown or a running capture cancels.
- Before the countdown can authorize, pending but unread events are drained, so
  a cancellation or input loss that arrived at expiry is processed first.
- Device disconnect (EOF/`ENODEV`/`EIO`/`ENXIO`) removes that reader. While
  waiting it returns to waiting and the overall timeout still applies; during
  the countdown or a running capture it cancels. A capture is never triggered by
  a disconnect.
- Timeout, cancellation and signal cleanup all still release grabs and reap the
  capture process group.

## Capture monitoring

The authorized command is started as its own session/process group and is
**not** waited on inline. The select loop keeps running, so:

- A Volume Down or input disconnect during the capture cancels it: the tool
  sends `SIGINT` (which libcamera's `cam` handles) then `SIGTERM`/`SIGKILL` only
  to that owned group, and reports `cancelled` with `during-capture`.
- Only when a capture has already exited is its return code used, reporting
  `complete` or `capture-failed`; a late cancellation does not overwrite a
  finished result.
- `--capture-timeout` bounds a capture that never exits and is reported as
  `capture-failed` with `timeout`.
- No other process is signalled: group membership is resolved from the capture
  leader's process group.

When `--` is omitted, the gate reports `authorized` and exits without running
anything, leaving the caller to start the capture off the readiness line.

## Optional exclusive grab

`--grab` is off by default, which is the safe choice for a disposable
multi-user liveboot where other consumers may legitimately read volume keys.
When enabled:

- Only devices that advertise a required key are grabbed.
- A grab failure (for example `EBUSY`) is reported as a warning and is not
  fatal; the gate continues with normal reads.
- Every successful grab is released in a `finally` block, so cancellation,
  timeout, disconnect, or `SIGINT`/`SIGTERM` cannot leave a device grabbed.

## Integration contract

The gate exposes a deliberately small surface so it can wrap either capture
path without inventing a UI framework.

**Shared wrapper pattern.** Put the real capture in a wrapper script or command,
pass it after `--`, and let the gate run it once. The wrapper can also be driven
by the readiness line instead: run the gate with no command and start the
capture when `state=authorized` appears (or when `--status-file` shows it).

**libcamera.** Wrap the existing `cam-system-heap`/`power-state.py` flow:

```sh
python3 wait-for-ready.py --timeout 120 --settle 4 --log /var/tmp/ready/cam.log -- \
    sudo /path/to/camera-tests/cam-system-heap -c "$REAR" \
    --stream role=still,width=1280,height=960,pixelformat=RGB888 \
    --capture=1 --file=/var/tmp/ready/rear-#.ppm
```

Keep the release check (`power-state.py --require-released`) in the surrounding
harness, before and after this gate. The gate only authorizes the shot.

**Megapixels.** Drive the existing session action from a wrapper, because the
gate must not build a UI. For example, have the wrapper send the installed
app's capture action, optionally with the existing `--pointer-tool` activation
path used by `run-megapixels.py`:

```sh
cat > /var/tmp/ready/megapixels-shot.sh <<'EOF'
#!/bin/sh
exec gdbus call --session --dest me.gapixels.Megapixels \
  --object-path /me/gapixels/Megapixels --method \
  org.gtk.Actions.Activate capture '[]' '{}'
EOF
chmod +x /var/tmp/ready/megapixels-shot.sh
python3 wait-for-ready.py --timeout 120 --settle 4 -- /var/tmp/ready/megapixels-shot.sh
```

A readiness cue for an existing UI can be wired without touching this tool:

```sh
python3 wait-for-ready.py --timeout 120 --settle 4 \
    --status-file /run/user/1000/pocketfed-camera-status \
    --notify /usr/bin/notify-send --quiet
```

`--notify` receives `(state, detail)` as its last two arguments and is bounded
to two seconds; failures are ignored.

## Tests

`python3 test-wait-for-ready.py` runs focused regressions without hardware or
camera access:

- Parses real native `struct input_event` bytes, including a structure split
  across two reads from an actual pipe, and detects `SYN_DROPPED`.
- Verifies evdev drop semantics: events between `SYN_DROPPED` and the boundary
  `SYN_REPORT` are suppressed (including across reads) and a `RESYNC` is
  emitted at the boundary. A regression feeds a stale press/release in that
  window and proves, end to end, that it does not authorize.
- Proves a failed `EVIOCGKEY` resync fails closed, and that a device with
  unknown initial state is excluded (`probe_initial_state`).
- Matches gestures per device, so a press on one node and release on another do
  not authorize.
- Drives the full runner through real `select()` and a real pipe: a writer
  thread emits the press/release and the authorized command runs once.
- Runs a real long-lived capture child and then feeds Volume Down, proving the
  child group is stopped, exit code is `2`, and the log says `during-capture`.
- Proves a pending cancellation at countdown expiry is drained and the command
  never starts (`before-capture`), and that timeout/disconnect never capture.
- Checks `--grab` is attempted before reading and released afterwards, is
  non-fatal when `EVIOCGRAB` fails, and that `run_capture` reaps a process group
  that ignores `SIGTERM` on timeout. Verifies the private status file mode and
  single-line bounding.

These are synthetic checks; they do not prove a device boot, a real key event,
or capture quality. A native trial still needs the executive to supervise the
physical run.
