# Software ISP metering investigation

Source examined: libcamera v0.7.2, commit
`191e202178f02430b5942397c70d215cdd2056fa`. This is a source finding, not an
accepted image-quality fix. The IMX363 tuning patch changes no metering code.

The stock Fedora rear capture used `DebayerEGL`, with a 4032×3024
RGGB-10-CSI2P input (5040-byte stride) and a 1280×960 XRGB8888 output. Its JPEG
was overexposed and strongly cyan; it pictured a monitor, so it is not printed
target acceptance.

In `src/libcamera/software_isp/debayer_egl.cpp`, `configure()` passes
`Rectangle(window_.size())` to the statistics code: a rectangle at (0, 0) with
the output dimensions. `process()` supplies the complete raw buffer without
applying the computed central-window offset. `SwStatsCpu` consequently samples
the raw top-left 1280×960 region, about 10% of this input image.

The EGL renderer instead scales the full input texture into the output. Its
projection and input-sized viewport produce a small right/bottom crop for these
dimensions, not the central 1280×960 crop suggested by `window_`. The CPU
debayer path does apply that central offset to its source pointer, so its
rendering and statistics cover a different field of view.

Thus the EGL statistics and displayed field of view differ. This can affect
automatic exposure and white balance, but it has not been established as the
cause of the observed clipping or colour cast. A CPU/GPU comparison also changes
composition, so it cannot isolate metering by itself.

Next checks, each behind the physical readiness gate:

- Capture with the pinned IMX363 tuning before changing metering code; preserve
  the original JPEG, negotiated stream and exposure/colour-gain observations.
- Compare a target filling the frame with one surrounded by a dark area, and
  include a uniformly lit field. Keep distance and lighting recorded.
- If testing a source correction, meter the full input rectangle in the EGL
  path and leave its projection/viewport unchanged. This increases statistics
  work by roughly tenfold at these dimensions, so measure frame rate and CPU
  cost as well as image quality.

Useful log categories in this version are `SoftwareIsp`, `Debayer`,
`SwStatsCpu`, `eGL`, `IPASoftAwb`, `IPASoftExposure` and `IPASoftBL`.
`LIBCAMERA_SOFTISP_MODE=cpu|gpu` selects the backend; confirm the actual selected
backend in the log. No metering correction is included in native iteration 2.
