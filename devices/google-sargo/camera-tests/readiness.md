# Camera readiness gate

`wait-for-ready.py` is a small, self-contained gate for the Sargo camera trial.
The phone starts face-down, so no test may capture until the operator has picked
it up, aimed the rear camera, and explicitly signaled readiness with a hardware
button. Readiness is **never** inferred from elapsed time.

After the operator gives a fresh **Volume Up press+release**, the gate waits a
short settling/countdown interval so there is time to hold still, then
authorizes exactly one capture command. **Volume Down** cancels at any point,
including during the countdown. Repeats and keys already held when the gate
starts cannot authorize a capture.

This file documents the tool; it does not modify the existing trial harness
(`README.md`, `run-megapixels.py`, `run-libcamera.py`, `power-state.py`).

## What it does and does not do

- Discovers capable input devices through the Linux evdev API only:
  `EVIOCGBIT` for the key bitmap, `EVIOCGKEY` for keys already down, and
  `EVIOCGNAME` for a label.
- Never reads or writes arbitrary GPIO and never accesses
  `/sys/kernel/debug/gpio` (a broad debug read there previously coincided with
  a kernel lockup on the `.8` kernel).
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
| `cancelled` | Volume Down, SYN_DROPPED or input loss; no capture run. |
| `timeout` | No fresh Volume Up within `--timeout`; no capture run. |
| `capturing` | Running the single capture command. |
| `capture-failed` | The command timed out, failed, or left live processes. |
| `complete` | The single capture command finished. |

Exit status: `0` authorized (and any command succeeded), `2` cancelled,
`3` timed out, `4` capture command failed, `130` interrupted.

`detail` and `instruct` are whitespace-collapsed and truncated, so a log parser
can treat the line as bounded tokens.

## Authorization state machine

A capture is authorized only by a **fresh** `KEY_VOLUMEUP` press (`value=1`)
followed by its release (`value=0`):

- `KEY_VOLUMEDOWN` press cancels immediately.
- `value=2` (repeat) events are ignored and never authorize.
- Keys already down when the gate starts (`EVIOCGKEY`) are ignored until they
  are released, and their release does not authorize. A later fresh press is
  still required. This covers the case where a volume key is held during start.
- `SYN_DROPPED` invalidates any partial gesture and drops pending state; the
  runner then re-reads `EVIOCGKEY`. It never authorizes, and during the settling
  countdown it cancels rather than risk a stale capture.
- Device disconnect (EOF/`ENODEV`/`EIO`/`ENXIO`) removes that reader. During the
  countdown it cancels; while waiting it returns to waiting and the overall
  timeout still applies. A capture is never triggered by a disconnect.
- Timeout, cancellation and signal cleanup all still release grabs and reap the
  capture process group.

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
- Drives the full runner through real `select()` and a real pipe: a writer
  thread emits the press/release and the authorized command runs once.
- Exercises the state machine failure cases directly: repeats, releases without
  a fresh press, initially held Volume Up/Down, Volume Down cancelling while
  waiting and while settling, `SYN_DROPPED` discarding a partial press and
  cancelling a settle, disconnect during settle, and timeout.
- Runs the bounded runner with injected readers/clock/select to prove the
  capture command runs exactly once, never on timeout or disconnect, and that a
  `--grab` is attempted before reading and released afterwards (and is
  non-fatal when `EVIOCGRAB` fails).
- Uses real child processes to prove `run_capture` reaps a process group that
  ignores `SIGTERM` on timeout and leaves no live helpers; verifies the private
  status file mode and single-line bounding.

These are synthetic checks; they do not prove a device boot, a real key event,
or capture quality. A native trial still needs the executive to supervise the
physical run.
