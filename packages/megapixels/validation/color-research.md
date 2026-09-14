# Pixel 3a color calibration research — 2026-09-10

Recommendation: judge a real saved JPEG and its retained DNG from the current trial before adding a profile. The renderer and saved-image pipeline differ. No camera profile has been generated, installed, or published; no phone state was changed.

## A concrete same-phone reference exists

The maintained raw.pixls.us sample repository lists sample **3496**, Google Pixel 3a, uploaded 2019-10-20, with an explicit **CC0-1.0 public-domain dedication**. Its primary EXIF metadata identifies `Google Pixel 3a`, HDR+ `1.0.265696846zd`, 4032×3024 raw CFA image, 4.4 mm f/1.8 rear camera. It includes these row-major XYZ→reference-camera matrices, each numerator divided by 10000:

- ColorMatrix1, CalibrationIlluminant1=20 (**D55**): `[10598, -5058, -1606; -9956, 19269, 401; 642, -2328, 12123]`.
- ColorMatrix2, CalibrationIlluminant2=17 (**Standard A**): `[16298, -7708, -2489; -9956, 19269, 401; 482, -1686, 8591]`.
- Both CameraCalibration matrices and AnalogBalance are identity. ProfileName is Embedded; ProfileEmbedPolicy=0. There are no ForwardMatrix tags in the EXIF listing.

Sources:

- Index/API with per-file CC0 link: <https://raw.pixls.us/json/getrepository.php?set=all>
- Metadata: <https://raw.pixls.us/getfile.php/3496/exif/IMG_20190918_164153.dng.exif.txt>
- Sample: <https://raw.pixls.us/getfile.php/3496/nice/Google%20-%20Pixel%203a%20-%2016bit%20(4:3).dng>
- Repository-advertised sample SHA256: `78c7bec867f3f739d43df6f027fad36ead73502d062570ce6ca14f59cdc4a0dd`. **Not independently verified: only index and EXIF downloaded, not image bytes.**

This is a documented source of same-phone calibration coefficients, not a maintained ready-made DCP. It is an HDR+ computational DNG with 16-bit storage and BGGR arrangement, unlike our raw10 RGGB capture; channel-order/orientation differences do not themselves change the meaning of RGB camera color matrices, but optical mode, gains, processing and actual color must be verified. Do not copy its scene-dependent AsShotNeutral, black levels, crop, or gain-map opcodes into our camera configuration.

No Pixel/Google entry was found in current LibRaw `src/tables/colordata.cpp`, RawTherapee `rtengine/camconst.json` / `dcraw.c` / `rtdata/dcpprofiles`, or rawspeed `data/cameras.xml`. RawTherapee inventory was pinned to `498f623784e33fd9a7077fcd8937fe0734033366`. This limited search does not establish that none exists anywhere.

The pmOS CC0 `imx363.yaml` supplies post-WB camera→RGB CCMs. It is not a DNG ColorMatrix; inverting and storing one directly loses its white-point/WB interpretation. The same-phone DNG coefficients above provide clearer semantics if a DCP is later needed.

## What affects which output

Source versions audited: Megapixels 2.1.0 `5fb1f24f1aeef80ea18224ab5829fda85653a4e8`; libmegapixels 0.2.3 `d50bf166972df4252d127f72f90986892f3cd901`; libdng 0.2.2 `438df53ee06d9f21202e0398c90a9c3bf9e86591`. Local package patches do not presently change color math.

| Finding | Preview | Saved DNG / JPEG |
| --- | --- | --- |
| GL matrix multiplication order | Direct effect | No direct effect on raw pixels, but AAA/white-balance metadata inherit preview feedback |
| DNG ColorMatrix applied to already rendered RGB in AAA | Feedback uses incompatible color spaces, especially with nonidentity DCP | Changes exposure / white balance inferred for capture |
| Correction gains written as AsShotNeutral | No direct effect | DNG white balance is inverted; affects `dcraw -w` JPEG and editors honoring camera WB |
| Identity ColorMatrix fallback | Permits uncalibrated feedback | Saved DNG has no physical camera calibration; `+M` asks dcraw to use it |
| Missing calibration illuminants in parsed/exported profiles | No temperature interpolation exists in GL path (matrix1 only) | Dual-illuminant DNG interpretation cannot be reliably preserved |

### Preview and AAA

`src/gles2_debayer.c:180-184` computes `W * F * A * S` using conventional row-major `multiply_matrices()`, where W is WB gain, F is the DNG forward matrix, A adapts D50→D65, and S is XYZ D65→sRGB. `glUniformMatrix3fv(..., GL_FALSE, ...)` interprets those floats as column-major, and `data/debayer_packed.frag:55` multiplies a row-vector `color *= color_matrix`. These two transpositions cancel: the CPU matrix acts on a column color. The required DNG order is `S * A * F * W`, so the current composition order is reversed. This affects preview/video output, not raw saved samples.

`numeric-audit.py` compiles and calls the actual production `matrix.c` multiplication. With a synthetic D50-referred sRGB camera (NOT an IMX363 profile), a neutral raw pixel `[0.25, 0.5, 1/3]` and WB gains `[2,1,1.5]` should render `[0.5,0.5,0.5]`; current order yields `[0.551285,0.514130,0.462557]`. This isolates a math issue without claiming actual image quality. The existing fallback also treats `sRGB_to_XYZD65` as a D50 forward matrix: neutral `[0.5,0.5,0.5]` produces `[0.521937,0.506783,0.639688]` before feedback/gamma.

`src/process_pipeline.c:555` reads rendered RGBA bytes, then passes DNG ColorMatrix1 to `libmegapixels_aaa_software_statistics()`. `libmegapixels/src/aaa.c:91-93` multiplies these already converted RGB statistics by the XYZ→camera matrix. Using the reference D55 ColorMatrix on neutral display RGB `[128,128,128]` produces `[50.3552,124.3392,133.5936]`, causing the next WB update to disturb neutrality. Matrix2 is stored but unused. A raw-statistics path, or an explicitly derived inverse rendering transform in linear space, would need separate design; inserting a real DCP alone can make this feedback worse.

### Saved DNG and JPEG

For these Bayer cameras, `save_dng()` writes raw sensor frames and metadata; it does not save GL-rendered pixels. The bundled `data/postprocess.sh:45-110` converts `1.dng` using `dcraw +M -H 4 -o 1 -q 3 -T -w` or `dcraw_emu` (latter branch adds `-fbdd 1` but does not request `-w`), then ImageMagick sharpens/contrasts the TIFF and encodes JPEG. The installed converter branch must be checked before attributing a JPEG difference to camera WB. Embedded profile settings affect the raw converter independently of preview rendering.

`src/process_pipeline.c:1122` passes preview correction gains directly to `libdng_set_neutral()`; `libdng/src/libdng.c:193-201` stores them unchanged and `:459` writes AsShotNeutral unchanged. For gains `[2,1,1.5]`, correct neutral is `[0.5,1,2/3]`, not `[2,1,1.5]`. A neutral raw pixel `[0.25,0.5,1/3]` then becomes `[0.125,0.5,0.2222]` after inverse stored WB instead of `[0.5,0.5,0.5]` (before color transform/normalization). If a saved JPEG has opposite WB to preview, inspect the DNG tag first and compare conversion with explicit gains. This is a small targeted potential fix, independent of choosing a calibration profile.

`src/dcp.c:125-141` copies color/forward matrices and tone curve but drops parsed illuminants. `save_dng()` passes no illuminants and the libdng writer does not write CalibrationIlluminant1/2. A future dual-illuminant profile needs this metadata handling repaired as well.

## Next decision

1. Retain the actual trial DNG + saved JPEG and inspect JPEG visually alongside preview. Extract ColorMatrix1/2, ForwardMatrix1/2, AsShotNeutral, AnalogBalance, black/white levels, CFA and illuminants.
2. If JPEG has a WB mismatch, verify the converter branch and compare an offline copy using reciprocal preview gains before introducing a DCP.
3. If color is sufficiently usable, leave rendering/calibration as follow-up work. If a profile is necessary, the same-phone CC0 DNG ColorMatrix coefficients are a supported starting point; derive D50 ForwardMatrix explicitly, preserve illuminant metadata, and decouple AAA from DNG matrix interpretation. Validate with a known neutral/colorful subject under daylight and indoor light. No present claim of calibrated color accuracy.

References for semantics:

- Adobe DNG 1.7.1.0, ColorMatrix pp32–33, AsShotNeutral p36, color mapping pp100–103: <https://helpx.adobe.com/content/dam/help/en/camera-raw/digital-negative/jcr_content/root/content/flex/items/position/position-par/download_section_733958301/download-1/DNG_Spec_1_7_1_0.pdf>
- Khronos glUniform matrix layout: <https://wikis.khronos.org/opengl/GLAPI/glUniform>
- Megapixels source: <https://gitlab.com/megapixels-org/Megapixels/-/tree/5fb1f24f1aeef80ea18224ab5829fda85653a4e8>
- libdng source: <https://gitlab.com/megapixels-org/libdng/-/tree/438df53ee06d9f21202e0398c90a9c3bf9e86591>
- libmegapixels source: <https://gitlab.com/megapixels-org/libmegapixels/-/tree/d50bf166972df4252d127f72f90986892f3cd901>
