# Sargo camera prior-validation summary

Honest state of the Pixel 3a (Sargo) rear-camera work as of 2026-09-10, before
the current local liveboot-first trials. Raw device logs, boot identities,
private screenshots and scene files are intentionally not committed here.

## What was actually observed

- **Two real rear Megapixels JPEGs existed.** With manual sensor flip
  correction and libmegapixels release 2, the release-4 app produced a 3024x4032 JPEG plus retained
  DNG through the private UI harness. The target was blurred and had a strong
  green cast, so neither printed-text readability nor colour passes. One
  earlier structurally valid capture was almost black because the camera was
  not facing the target.
- **Image quality and reliability are unfinished.** No release-5 image was
  captured. Repeated capture, app close/reopen, suspend/resume and reboot
  acceptance remain outstanding. A later camera transport stall (no frames
  after STREAMON) reproduced across Megapixels, `megapixels-getframe` and
  libcamera. A broad `/sys/kernel/debug/gpio` read was followed by a kernel hang;
  the exact cause was not established.
  Do not repeat that read.
- **Native app release 5 was built but produced no live image.** It stores the
  reciprocal preview white-balance gains in DNG `AsShotNeutral`; its regression
  rejects release 4. Build/install passed; live validation is pending.
- **libmegapixels release 3 fixes the Bayer order but does not prove capture.**
  It negotiates sensor flip controls to match the requested RGGB10 phase before
  propagating formats. A device trial reached STREAMON without EPIPE, but no
  frames arrived, so it establishes layout correction only.
- **libcamera (separate diagnostic) was not an image-quality pass.** Running
  `cam` in a private mount namespace exposing the system DMA heap produced
  three rear RGB frames on the first burst; colour was unsettled and the frames
  were green/blurry. Ordinary libcamera failed software-ISP frame allocation.

## Kernel lens-driver fix

The LC898219XI open path restored controls before acquiring the runtime-PM
reference. The `.9` driver fix builds, passes its lifecycle regressions with an
original-source negative control, compiles with `W=1` for AArch64,
`checkpatch.pl --strict` is clean, and an SRPM plus an isolated COPR trial build
passed signature verification. No `.9` kernel was deployed or booted on the
device; the temporary native module that was loaded ran against the packaged
`.8` kernel. Physical focus, autofocus and power consumption are unvalidated.

## Local regressions

The source regressions in this tree were re-run against freshly extracted,
pinned upstream archives (`sources.sha256` verified) with the patches applied:

- Megapixels: calibration lookup, finite blank-frame queue, software/manual
  controls, empty-dequeue handling, capture burst state, stream generation and
  reciprocal DNG white balance.
- libmegapixels: Bayer-order negotiation and rollback.
- kernel: LC898219XI lifecycle and fault injection.
- Device helpers: `test-power-state.py` and `test-libcamera-runner.py`.

All passed. The app, libmegapixels and kernel source regressions also rejected
the unpatched sources used as negative controls.
A passing source regression is not a successful camera capture.

## Current test path

Subsystem work now uses the local `tools/liveboot` kboop/fastboop flow with a
cached userspace fixture and USB-root boot. Public CI, COPR publication, an
OSTree deployment and installation images are promotion steps after a
subsystem works; they are not prerequisites for an ephemeral camera trial.
