# libcamera simple-IPA IMX363 tuning provenance

`patches/0001-simple-imx363-tuning.patch` adds the pinned IMX363 tuning YAML to
the libcamera **simple (software ISP) IPA** and registers it for install. It is
the only change in the patch and touches two paths:

- new `src/ipa/simple/data/imx363.yaml`
- `src/ipa/simple/data/meson.build` (adds `'imx363.yaml',` to `conf_files`)

Nothing else is modified. No sensor helper, gain equation, delay or lens
mapping is changed.

## Pinned input

| Field | Value |
| --- | --- |
| Local input | `devices/google-sargo/camera-trial/inputs/imx363.yaml` |
| License | `CC0-1.0` (SPDX header preserved verbatim) |
| SHA-256 | `0d0cf3d08412b177724c4b1a100313c38fccd6ee8f8ce171d3522ed68fd46ed6` |
| Bytes | copied unchanged; no reformatting |

Immutable upstream source (identified by the provenance audit, not re-fetched
here):

- Project: postmarketOS `pmaports`
- Commit: `fd540e80175206ef6e917583e242814bf4b81b32`
- Path: `temp/libcamera/imx363.yaml`
- Raw URL: `https://gitlab.com/postmarketOS/pmaports/-/raw/fd540e80175206ef6e917583e242814bf4b81b32/temp/libcamera/imx363.yaml`
- Audit note: that commit carries the `temp/libcamera` upgrade to libcamera
  0.7.2 by RobertMader and introduced `temp/libcamera/imx363.yaml` with the
  current six CCMs.

## Source verification (0.7.2 source, no hardware)

Verified against `/tmp/libcamera-source-20260914` (libcamera `version : '0.7.2'`):

- **Patch applies cleanly.** `patch -p1 --dry-run` against the exact
  `src/ipa/simple/data/meson.build` reports both files; a real apply succeeds.
- **Result equals the pinned input.** After applying, `cmp` of the resulting
  `src/ipa/simple/data/imx363.yaml` against the pinned input is byte-identical,
  and its SHA-256 is the pinned value above.
- **Valid YAML.** The document parses (ruamel safe loader): top-level keys
  `version` (int) and `algorithms` (list).
- **Schema matches the 0.7.2 simple IPA.**
  - Algorithm names are the exact registry strings from
    `REGISTER_IPA_ALGORITHM(...)`: `BlackLevel` (`blc.cpp`), `Awb` (`awb.cpp`),
    `Ccm` (`ccm.cpp`), `Adjust` (`adjust.cpp`), `Agc` (`agc.cpp`); each YAML
    entry is a single-key map.
  - `BlackLevel.blackLevel` is an integer, read as `int16_t` in `blc.cpp`.
  - `Ccm.ccms` is a list of `{ ct, ccm }`; `ccm.cpp` calls
    `Interpolator<Matrix<float,3,3>>::readYaml(..., "ct", "ccm")`
    (`src/ipa/libipa/interpolator.h`), so `ct` is a numeric scalar and `ccm` is
    a nine-element numeric matrix. This file has six such entries.
  - `Awb`, `Adjust` and `Agc` ignore tuning data in this release.
- **Selection path.** The software ISP selects `<sensor model>.yaml` with an
  `uncalibrated.yaml` fallback (`src/libcamera/software_isp/software_isp.cpp`),
  and `soft_simple.cpp` reports the IPA module name `simple`. Installing
  `imx363.yaml` under `ipa_data_dir/simple/` (the `data/meson.build`
  `install_dir`) therefore makes it the IMX363 tuning file.

`yamllint` (default style) flags the pinned file's aligned matrix columns
(bracket/comma spacing, indentation). Those are cosmetic style rules, not
validity errors; the bytes are intentionally preserved.

## Status and limits

- **Colour is still unvalidated.** The six CCMs are the upstream CC0-1.0 data
  recorded above; this patch makes no claim of measured calibration or of
  colour accuracy on Sargo.
- No sensor helper, analogue-gain equation, delay or lens mapping is changed;
  those require empirical validation and are out of scope here.
- The patch was built into the `4.fc46.native.1` iteration, which **finished**
  on the phone and passed 20 selected non-camera libcamera library tests. That
  iteration was **not installed** and no camera ran it, so the added CCMs are
  still unvalidated in a capture. The iteration also has an unrelated IPA-module
  signature defect (see the [native RPM README](README.md)), so it must not be
  installed as-is; rebuilding with the corrected re-sign glob is the next step
  before a tuning comparison.
