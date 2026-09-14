# qcam bounded one-shot save (patch 0002)

`patches/0002-qcam-bounded-save.patch` is an optional libcamera 0.7.2 change to
the `qcam` GUI test application. It adds two explicit options so a phone trial
can warm up for a bounded number of frames, save one image, and exit without
touch interaction. It reuses qcam's existing Qt image writer and is independent
of the tuning patch `0001-simple-imx363-tuning.patch`.

## Options (patch-added, not upstream)

- `--output FILE` — write one image to `FILE` after the frame count, then exit.
- `--after-frames N` — number of rendered viewfinder frames before the save,
  `1..1800` (about one minute at 30 fps).

Short forms `-o`/`-a` exist because qcam option ids are single characters;
prefer the long forms.

## Validation (in `main.cpp`, before the camera is started)

- `--output` and `--after-frames` must be given **together**; one alone fails.
- `--after-frames` is declared `OptionString` and parsed by the shared strict
  parser `MainWindow::parseAfterFrames()`:
  - reject empty input;
  - require every character to be an ASCII digit (`0x30..0x39`), which rejects
    signs, leading/trailing whitespace, hex, exponents and non-ASCII digits;
  - convert with `QString::toUInt(&ok, 10)` and reject when `!ok` (overflow does
    not wrap) or outside `1..kMaxAutoSaveFrames` (`1800`).
  `OptionInteger` was deliberately not used: it parses via `strtoul` into
  `unsigned int` with unchecked narrowing, so e.g. `4294967297` would become `1`.
- `--output` must be non-empty.
- the renderer must be `qt` (the default). `-r gles` is rejected because the GL
  viewfinder's `getCurrentImage()` is a scaled widget framebuffer, not the
  full-resolution frame.

With neither option, qcam's interactive behaviour is unchanged.

## Behaviour and exit codes

- The save fires once from `MainWindow::processViewfinder`, immediately after
  `viewfinder_->render()`, once `framesCaptured_ >= afterFrames_`. The Qt
  viewfinder sets its `QImage` inside `render()` before emitting
  `renderComplete`, so `getCurrentImage()` returns the just-rendered frame at
  the **full stream resolution**.
- The write reuses `QImageWriter` with quality 95; the interactive "Save As…"
  path was refactored to call the same `saveImage()` so both are identical.
- On success: `quit()` → `app.exec()` returns 0.
- On write failure: the actual writer error is logged
  (`qWarning() << ... << lastSaveError_`) before
  `QCoreApplication::exit(EXIT_FAILURE)`; a failed write is never reported as
  success and is attempted only once (`saved_` guard).

## Usage

qcam needs a Wayland compositor; this patch does not add one (Phoc harness is a
separate iteration). Run it as the single command of the readiness gate under a
compositor. Pin the **stable rear camera id** so the default front camera is not
picked (`main_window.cpp` resolves `-c` through `CameraManager::get`, i.e. an
exact `Camera::id()` match):

```sh
qcam -c /base/soc@0/cci@ac4a000/i2c-bus@0/camera@1a -r qt \
    --stream role=viewfinder,width=1280,height=960,pixelformat=RGB888 \
    --output /var/tmp/pocketfed-qcam/frame.jpg --after-frames 90
```

`.jpg`/`.png` is selected from the file name extension by `QImageWriter`.

## Focused parse verification

Verified by construction against the code and documented cases (no test
framework; Qt dev headers were not available locally, so the compiled result
must be confirmed at native build):

| Input | Result | Reason |
| --- | --- | --- |
| `1`, `90`, `1800`, `0005` | accepted | ASCII digits, in range |
| `0` | rejected | below minimum |
| `1801` | rejected | above maximum |
| `4294967297` | rejected | `toUInt` overflow, `ok == false` |
| `-1`, `+5`, ` 5`, `5 `, `0x10`, `1e3`, `1.0` | rejected | non-digit characters |

## Provenance and verification

- Source: `/tmp/libcamera-source-20260914` (libcamera `version : '0.7.2'`).
- Touches only `src/apps/qcam/main.cpp`, `src/apps/qcam/main_window.h`,
  `src/apps/qcam/main_window.cpp`.
- `patch -p1 --dry-run` and `git apply --check` both succeed, and a real apply
  succeeds with `0001-simple-imx363-tuning.patch` present (disjoint files).
- Uses only existing APIs: `OptionsParser::addOption`,
  `OptionValue::toString`, `QString::fromStdString`, `QChar::unicode`,
  `QString::toUInt`, `QImageWriter`, `QCoreApplication::exit`,
  `viewfinder_->getCurrentImage()`.

## Limitations needing native compile/test

- Not compiled or run here. Build against the phone's libcamera 0.7.2 + Qt 6 and
  exercise on test-sargo.
- The Qt JPEG image format plugin (`libqjpeg.so` from `qt6-qtbase-gui`) must be
  present for `.jpg` output.
- The real default/adjusted viewfinder size on Sargo is not asserted; pin
  `--stream` explicitly.
- `--after-frames` is a calibration parameter (a small value may save an
  unsettled first frame). `1800` is only a hard cap; the **caller must enforce a
  wall-clock timeout** (for example the gate's `--capture-timeout`).
- `QImageWriter` overwrite/permission behaviour for an existing `--output` path
  was not verified on device.
- No orientation handling: a mounted-rotated preview is a pipeline/compositor
  concern, not addressed by this patch.

## Non-goals

No orientation patch, no new frontend, no Phoc/compositor harness, and no change
to the tuning patch or tuning data. This is a separate iteration after the
currently building tuning-only candidate.
