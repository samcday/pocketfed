# qcam bounded one-shot save (patch 0002)

`patches/0002-qcam-bounded-save.patch` is an optional libcamera 0.7.2 change to
the `qcam` GUI test application. It adds two explicit options so a phone trial
can warm up for a bounded number of frames, save one JPEG, and exit without any
touch interaction. It reuses qcam's existing Qt image writer; it is independent
of the tuning patch `0001-simple-imx363-tuning.patch`.

## Options (patch-added, not upstream)

- `--output FILE` — write one image to `FILE` after the frame count, then exit.
- `--after-frames N` — number of rendered viewfinder frames before the save
  (`1..100000`).

Short forms `-o`/`-a` exist because qcam option ids are single characters;
prefer the long forms.

Validation happens in `main.cpp` before the camera is started:

- `--output` and `--after-frames` must be given **together** (one alone fails).
- `--after-frames` must be in `1..100000`.
- `--output` must be non-empty.
- the renderer must be `qt` (the default). `-r gles` is rejected because the GL
  viewfinder's `getCurrentImage()` returns a scaled widget framebuffer, not the
  full-resolution frame.

With neither option, qcam's interactive behaviour is unchanged.

## Behaviour and exit codes

- The save is triggered once from `MainWindow::processViewfinder`, immediately
  after `viewfinder_->render()`, once `framesCaptured_ >= afterFrames_`. The Qt
  viewfinder sets its `QImage` inside `render()` before emitting
  `renderComplete`, so `getCurrentImage()` returns the just-rendered frame at
  the **full stream resolution**.
- The write reuses `QImageWriter` with quality 95, the same writer the
  interactive "Save As…" path uses. `saveImageAs` was refactored to call the
  shared `saveImage()` so both paths are identical.
- On success: `quit()` → `app.exec()` returns 0.
- On write failure: `QCoreApplication::exit(EXIT_FAILURE)` → `app.exec()`
  returns nonzero. A failed write is never reported as success, and the save is
  attempted only once (`saved_` guard).

## Usage

qcam needs a Wayland compositor; this patch does not add one. Run it as the
single command of the readiness gate under a compositor (Phoc harness not part
of this iteration):

```sh
qcam -r qt \
    --stream role=viewfinder,width=1280,height=960,pixelformat=RGB888 \
    --output /var/tmp/pocketfed-qcam/frame.jpg --after-frames 90
```

`.jpg`/`.png` are chosen from the file name's extension by `QImageWriter`.

## Provenance and verification

- Source: `/tmp/libcamera-source-20260914` (libcamera `version : '0.7.2'`).
- Touches only `src/apps/qcam/main.cpp`, `src/apps/qcam/main_window.h`,
  `src/apps/qcam/main_window.cpp`.
- `patch -p1 --dry-run` and `git apply --check` both succeed, and a real apply
  succeeds with `0001-simple-imx363-tuning.patch` present in the same tree
  (the two patches touch disjoint files).
- Only existing qcam/libcamera/Qt APIs are used (`OptionsParser::addOption`,
  `OptionValue::toInteger/toString`, `QImageWriter`, `QCoreApplication::exit`,
  `QString::fromStdString`, `viewfinder_->getCurrentImage()`).

## Limitations needing native compile/test

- Not compiled or run here. It must be built against the phone's libcamera
  0.7.2 + Qt 6 and exercised on test-sargo.
- The Qt JPEG image format plugin (`libqjpeg.so` from `qt6-qtbase-gui`) must be
  present for `.jpg` output.
- The real default/adjusted viewfinder size on Sargo is not asserted; pin
  `--stream` explicitly. `--after-frames` is a calibration parameter: a small
  value may save an unsettled first frame.
- No orientation handling: if the preview is mounted-rotated, that is a
  pipeline/compositor concern, not addressed by this patch.
- `QImageWriter` overwrite/permission behaviour for an existing `--output` path
  was not verified on device.

## Non-goals

No orientation patch, no new frontend, no Phoc/compositor harness, and no change
to the tuning patch or tuning data. This is a separate iteration after the
currently building tuning-only candidate.
