# pipewire: gstpipewiresrc stall fixes for the Sargo camera trials

Fedora 46 ships pipewire 1.6.8-3. With GNOME Snapshot on the libcamera node
(`camerabin` + `pipewiresrc` + `gtk4paintablesink`), `pipewiresrc` logs
`buffer ... was not recycled` from the first seconds and stops delivering frames
about 19 s in; camerabin then accepts a second `start-capture` that never runs
and Snapshot stays in "Operation in progress" with the shutter disabled (trial
05, 15 September 2026; the same symptom as Mobian qcom-support issue 7).

Upstream fixed this after 1.6.8. The two commits in `patches/` are exact
cherry-picks (`git cherry-pick -x`) onto the `1.6.8` tag:

- `0001` `gstpipewiresrc: do not recycle a pool buffer with the loop lock held`
  (upstream 30ff8da17)
- `0002` `gstpipewiresrc: copy the last free buffer instead of stalling the stream`
  (upstream bf3951eb0)

A third upstream fix, `gst: pool: fix buffer release race condition`
(2770143f5), does not apply to 1.6.8 and was left out.

## Rebuild

Built from the signed Fedora source RPM `pipewire-1.6.8-3.fc45.src.rpm`
(sha256 `d40b8b64cfb4af593e02b23a29397a952adbc1addf9c02aa0be0de4c6254e3e6`) in
an aarch64 Fedora 46 container with the two patches appended as `Patch100`
and `Patch101`, `Release` suffixed `.pocketfed.gst.1`, and `rpmbuild -bb
--without onnx` (the only build dependency the container could not satisfy;
leave jack enabled or its man pages end up unpackaged). All pipewire
subpackages the image installs must be replaced together so the
version-locked `Requires` stay consistent.

## Result

With `pipewire-gstreamer-1.6.8-3.pocketfed.gst.1` on the disposable liveboot,
Snapshot took five consecutive photos behind one Volume Up press (trial 06) and
one more after a fresh start (trial 07); every JPEG decoded the QR target and
the strict release gate passed afterwards. The `not recycled` messages still
appear; the stream no longer stalls.

Retirement: drop this once Fedora ships a pipewire with those commits (1.6.9 or
later); track it in the upstreaming queue.
