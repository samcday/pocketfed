# Manual focus follow-up

The pinned libcamera v0.7.2 simple pipeline does not expose `LensPosition` or
`AfMode`, and qcam has no focus UI. `CameraSensor` discovers and opens the
ancillary lens, but the simple pipeline does not call
`CameraLens::setFocusPosition()`. The public `LensPosition` control is measured
in dioptres; raw actuator codes cannot honestly be passed through as distances.

Check kernel source against the actual candidate. The `.11` trial corresponds
to `132283913205a1db1d57fc3e563eea8224f5b79a`; its
[LC898219XI driver](https://github.com/samcday/linux/blob/132283913205a1db1d57fc3e563eea8224f5b79a/drivers/media/i2c/lc898219xi.c)
powers the lens before applying cached controls during `open()`, and unwinds
power on failure. An older `.7` checkout applies controls before power-up and
is not representative of this trial. The candidate lens module SHA-256 is
`4b86694fe8a51d1462c02b5127716826c31d13a9b21546a514b8f450e65c6db0`.

The driver exposes `V4L2_CID_FOCUS_ABSOLUTE` from 0 through 4095. Its signed
DAC conversion shifts by four bits, so many adjacent values select the same
position. Closing the final lens descriptor allows autosuspend after one
second; opening it again powers up and reapplies the cached control.

A bounded raw-code sweep is a possible diagnostic after the colour/preview
baseline. It must occur inside a physical readiness-gated session: discover the
exact lens through narrow sysfs name/dev mappings, open/query/set it after the
initial release check, retain ownership during capture, and close it before
the final release check. Record raw codes and several frames at each position;
the settling time and code-to-distance relationship have not been measured.
Do not wrap the entire existing session in a lens holder, since that would make
its initial release check fail.

A maintained libcamera implementation needs pipeline control plumbing and a
measured dioptre-to-code mapping, followed by UI support. Neither that feature
nor a raw-code helper is included in native iteration 2. Manual focus remains
part of the camera acceptance goal.
