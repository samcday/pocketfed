# Rear-camera acceptance target

`generate-target.py` produces a public, non-private A4 target and a PNG preview
for the Sargo rear-camera goal. Generated output under `output/` is not
committed; regenerate it as needed. The companion PNG is useful on another
display during setup. **A photograph of a display does not satisfy the
printed-text acceptance check.** The target includes upright/left/right labels,
an 18 pt reading paragraph, graded 18/16/14/12/10 pt text, six colour swatches,
five neutral steps, a 50 mm print-scale ruler, and a 65 mm QR symbol.

These helpers are intended to run inside a disposable local liveboot session
(see `tools/liveboot/README.md`); no installed deployment or publication is
required to use them.

The QR contains exactly this harmless text (it is not a URL):

```text
PocketFed sam-sargo camera test 2026-09-10
```

## Generate

Dependencies: Python 3 with `reportlab`; Poppler's `pdftoppm` on `PATH`.
Run from this directory:

```sh
python3 generate-target.py
```

The PDF uses embedded Bitstream Vera fonts bundled with ReportLab and vector
QR modules. The script fixes PDF timestamps and document IDs for repeatable
output with the same dependency versions; the 150 DPI PNG is rendered from that PDF.
`--output-dir PATH` and `--dpi 72..600` override preview settings.

## Capture and review

1. Print the PDF on A4 paper at **100% / actual size**. Measure the 50 mm ruler
   to check scaling. Keep the page flat in even, ordinary indoor light.
2. Hold the phone parallel to the page, with the rear camera facing it. Include
   all four page corners and fill most of the frame. Record distance and light
   conditions; avoid glare, motion blur and shadows across the page.
3. Use the phone UI to focus (manual focus is acceptable), expose and save a
   JPEG. Preserve the original saved JPEG and its metadata.
4. Run the checker below on the original JPEG. A match proves this payload was
   decoded from that saved image. Dimensions and EXIF are observations, not
   proof of correct orientation.
5. Open the saved JPEG in an ordinary image viewer that honours EXIF. Verify
   that TOP is upright, LEFT and RIGHT are correctly placed, and the text is
   not mirrored. At full resolution, read the complete paragraph and record
   the smallest graded line that is reliably readable. At least the full
   paragraph and 14 pt line should be readable for the initial target check;
   retain finer-size results to compare focus settings.
6. Compare the saved photo with the **actual printed page**: swatches should
   have plausible hues, the page should look neutral, and the neutral patches
   should remain visibly distinct. Printer and display output are not
   calibrated colour references. Note any cast, clipped highlights or muddy
   shadows rather than claiming quantitative colour accuracy.

Save a record alongside each JPEG: capture time, kernel/userspace versions,
capture tool, lens/focus setting, distance/light, paragraph readability,
smallest readable size, QR result, orientation and colour/exposure findings.
Do not label generated or re-encoded test fixtures as device captures.

## Validate a saved JPEG

Dependencies: Python `Pillow`, plus either `zbarimg` (Fedora package `zbar`) or
Python OpenCV (`opencv-python-headless`). NumPy is required with OpenCV.

```sh
python3 check-jpeg.py /absolute/path/to/original-capture.jpg
python3 check-jpeg.py --backend opencv /absolute/path/to/original-capture.jpg
```

The checker outputs JSON: stored/display dimensions, file size, EXIF
orientation, decoded QR values, and exact-payload match. It honours EXIF before
decoding, leaves the original untouched, and accepts JPEG files only. The
default decoder is `zbarimg` when installed, otherwise OpenCV. OpenCV attempts
native size and, for large images, reduced sizes to assist decoding.

Exit statuses: `0` = expected QR decoded; `1` = valid JPEG but expected QR not
decoded; `2` = invalid input, missing dependencies or decoder failure. A QR
failure does not diagnose the cause. A QR success **does not certify focus,
readable printed text, exposure, colour, orientation, camera power release or
capture reliability**.

After the initial page succeeds, repeat actual UI captures across repeated
capture, app close/reopen, suspend/resume and reboot. Record those outcomes
with the device's separate runtime-power checks; this target/checker does not
perform those lifecycle checks.

## Capture path and scope

The selected capture path is **libcamera** through the
[`libcamera-session/`](libcamera-session/README.md) helper: one bounded `cam`
session (via the sibling `cam-system-heap`) that writes a final-frame JPEG,
gated by [`wait-for-ready.py`](readiness.md) and bracketed by `power-state.py`.
It has no on-screen preview, so UI behaviour is not covered by it. The earlier
`run-libcamera.py` is a bounded multi-frame PPM diagnostic, not the selected
path. The Megapixels application and its packaging are out of scope for this PR
(retained only in the local archived branch), so the helpers here do not require
Phoc, gdbus or any camera app.

The acceptance goal is unchanged: a useful saved JPEG of the printed target
with a decodable QR, manual focus, plausible colour, correct orientation and
repeated capture, reopen, reboot and suspend/release behaviour.

## Camera release checks

Run `power-state.py` as root after closing all camera clients. It discovers
CAMSS's media node and camera nodes through sysfs, checks open descriptors by
device identity (including aliases), and observes sensor/lens runtime state
without opening the device nodes. Use the strict gate between close/reopen
cycles and after final close in the suspend/resume and reboot trials:

```sh
python3 power-state.py --require-released --timeout 10 > power-after-close.json
```

Exit status `0` requires both sensors and the lens to be discovered and
suspended, with no camera holders and complete root process visibility.
Status `1` means devices or holders remain busy; `2` means evidence is
incomplete. With no `--require-released`, the command reports observations
without asserting release. The bounded timeout lets runtime suspend settle.
Each report includes kernel and boot identity. This is kernel-state evidence,
not an electrical power measurement or proof of camera capture.

On the `.8` kernel, reading `/sys/kernel/debug/gpio` during the 2026-09-10
investigation was followed by a CPU stall, kernel lockup reports and loss of
SSH. Do not use that broad diagnostic read in camera testing. The responsible
GPIO controller has not been established. Read the narrow sysfs runtime-power
attributes used by `power-state.py` instead. When guarding a mutation, pass
`--require-released`; the default observation mode does not assert release.

`python3 test-power-state.py` exercises nine release-evidence cases, including
missing devices, unavailable state, incomplete process visibility, renumbered
media nodes and holders reached through a different pathname. Its safe alias
fixture uses `/dev/null`; it never opens camera nodes.

## Libcamera capture helpers and allocator diagnostic

The selected capture path is the
[`libcamera-session/`](libcamera-session/README.md) helper; the earlier
`run-libcamera.py` is a bounded multi-frame PPM diagnostic retained here.
`cam-system-heap` is the shared wrapper both use: it runs `cam` as root in a
private mount namespace exposing only the existing system DMA heap. The real
device nodes and permissions remain unchanged. This is a diagnostic for
libcamera's software ISP, which permits system memory but normally selects an
available CMA heap first. It is not a production launcher or a general fix for
pipelines requiring contiguous memory.

The diagnostic runner `run-libcamera.py` uses the two adjacent helpers:

```sh
sudo python3 run-libcamera.py --output ./camera-raw-run
```

The runner requires `libcamera`, `libcamera-tools`, `libcamera-ipa` and
ImageMagick. It checks release before capture, selects the stable rear identity
and asks for three 1280×960 RGB frames. It verifies all three saved PPM files,
including full pixel decoding and dimensions, then checks camera release again.
A zero exit from `cam` alone is insufficient: when the IPA was missing,
`cam` successfully received raw frames but its PPM writer rejected them.

The default capture timeout is 30 seconds (`--timeout 1..60`). On timeout the
runner first sends SIGINT to let cam release its resources. It then terminates
remaining members of that run's private process group, including orphaned IPA
helpers; it never kills all processes with a given name. Timeout, remaining
processes, missing/invalid output or a failed release check make the run fail.
Private logs, images and `result.json` remain in the new output directory.

`python3 test-libcamera-runner.py` checks real child-process cleanup and saved
pixel validation using synthetic fixtures, without camera access. These local
runner regressions passed; the runner itself still needs a native device trial
after recovery from the diagnostic kernel hang.

In the native 2026-09-10 trial, ordinary libcamera failed frame allocation;
the equivalent private-namespace test selected `/dev/dma_heap/system` and
saved three rear frames. The first three frames had unsettled colour and
were not a quality acceptance pass. Use the stable sensor identity because
rebuilding the media graph changed camera index 1 to Front.

## Artifact/helper verification (2026-09-10)

Generated with ReportLab 4.4.9 and Poppler 26.05.0. The PDF has one A4 page
(595.2756 x 841.8898 pt). Its 1241 x 1754 preview was visually inspected for
layout and legibility. Regeneration produced byte-identical PDF and PNG files.

Using Pillow 12.3.0 and OpenCV 4.13.0, the checker decoded the exact payload from
a JPEG exported from the preview and from a rotated copy carrying EXIF
orientation 6. It returned exit 1 for a blank JPEG and exit 2 for a PNG input.
These were generated helper fixtures, **not camera captures**. The optional
zbarimg backend has not yet been exercised in this environment.
