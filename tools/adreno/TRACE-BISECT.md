# Bisecting an Adreno GPU hang with apitrace

Recipe used to reduce the A306 GTK hang in
[pocketfed#80](https://github.com/samcday/pocketfed/issues/80) from a ~6260-call
captured frame to **two GPU operations**, on a board reachable only over UART.

The method needs no Mesa build, no kernel change, no trimmed trace files, and no
board reboot. The issue holds the trial results; this file is the procedure.

## Why `--ignore-calls` instead of `apitrace trim`

`eglretrace --ignore-calls=CALLSET` skips calls at replay time. Every bisect step is
then a different *command line* against one unchanged trace file, rather than a new
trace that has to be generated on the host and shipped to the board. On a serial-only
target that is the difference between one ~3.5-minute transfer and a dozen of them.
It also keeps every step exactly reproducible from the original input plus a flag.

Keep `eglSwapBuffers` in every step. Ignoring it means the batch is never submitted,
so the run trivially "passes" and the result is meaningless.

## Getting a retracer onto the target

Use the retracer from the **same build** as the capture wrapper, or replay differences
become a confounder. Verify the RPM against Koji's published digest before extracting:

```python
import xmlrpc.client
s = xmlrpc.client.ServerProxy("https://koji.fedoraproject.org/kojihub")
r = s.getRPM("apitrace-14.0-2.fc45.aarch64")
print(s.getRPMChecksums(r["id"], ["sha256"]))   # the "" key is the unsigned rpm
```

`rpm -Kv` should report `Header SHA256 digest: OK` and `Payload SHA256 digest: OK`
(signatures will be `NOTFOUND` for an unsigned Koji artifact). Then
`rpm2cpio ... | cpio -idmu`, and check `ldd` in the guest for missing libraries before
transferring. Push with [`uart/uart-push.py`](uart/README.md) and re-hash on arrival.

Fedora's `eglretrace` is built for **X11 only** — it links `libX11` and has no Wayland
GLWS. Under a wlroots compositor with Xwayland enabled, `/tmp/.X11-unix/X0` already
exists and `DISPLAY=:0` inside the session is enough.

Do **not** pass `-w`. It means "wait on finish", and keeps the window open
indefinitely instead of exiting. Without it the process exits on its own and prints
`Rendered N frames in T secs`, which is both a completion signal and a second oracle.

## The oracles

1. **Authoritative:** a kernel hangcheck for the replay process.
   ```sh
   journalctl -k -o short-monotonic | grep -E 'hangcheck detected|completed fence|submitted fence|offending'
   ```
   Check the `offending task:` line — the kernel prints the full cmdline, so it
   confirms *which* `--ignore-calls` set produced the hang.
2. **Secondary:** apitrace's own wall-clock line. In pocketfed#80 every pass rendered
   in 0.54–1.14 s and every hang in 3.1–4.0 s, the difference being hangcheck plus
   recovery. Useful, but it also moves when a shader has to be recompiled — a first
   run with a new `IR3_SHADER_DEBUG` value took 5.58 s while passing cleanly. Never
   call a hang from timing alone.

A GPU that self-recovers lets the replay finish and exit 0, so **exit status is not an
oracle**.

## Procedure

Before every run: same boot ID, CRTC `enable=1 active=1`, GPU `power/control=on` and
`runtime_status=active`, compositor alive. After every hang: confirm fences match
again (`last-fence == retired-fence`, `rptr == wptr` in `/sys/kernel/debug/dri/0/gpu`)
before starting the next.

1. **Confirm the unmodified trace reproduces** under the driver flags the original
   capture used. If it does, the reproducer no longer involves the application.
2. **Enumerate the draw window** from `apitrace dump`: every draw, clear, program
   switch and UBO rebind, with call numbers.
3. **Halve the draw set** and recurse into whichever half still hangs. Nine draws
   reduced to one in four replays.
4. **Run the negative control**: ignore *all* draws. If that still hangs, the draws
   were never the trigger and the bisect above is invalid.
5. **Remove the other operation classes** — clears, uploads — one class at a time,
   from the minimal draw set. This is what found that a scissored `glClear` was also
   required.
6. **Take the matched control** at minimal size, changing only the driver flag
   (`FD_MESA_DEBUG=sysmem` versus `sysmem,flush`). A pass/fail pair on two operations
   is worth far more than one on a whole frame.

Add `--markers` on a final capture run so call numbers appear in the command stream
for `cffdump`/`crashdec`. In pocketfed#80 it did not change the outcome.

## Capturing the hang

Prefer the **devcoredump** over `hangrd`:

```sh
cat /sys/class/devcoredump/devcd<N>/data > dump.txt   # then: echo 1 > .../data to clear
```

It carries the register file, ringbuffer and BO contents, and is small
(94–139 kB here, ~10–20 kB compressed). `/sys/kernel/debug/dri/0/hangrd` returned
0 bytes across repeated attempts even with a reader attached via `setsid` before the
hang, so do not plan around it.

## Look for a natural control in the trace

The strongest single result in pocketfed#80 came from noticing the frame already
contained two draws identical in program, clip mode, attribute layout, instance count
and scissor geometry, differing only in one UBO binding offset. Replaying each alone
tested that one variable with no reconstruction and no compiler involved. Before
building a synthetic reproducer, check whether the capture already holds the
comparison.

## Budget

Each replay is a chance to wedge the board. Decide the maximum number of starts in
advance, count interrupted starts, and record every step's exact call set and result
as you go — including the passes, which are what make a minimal set *minimal*.
