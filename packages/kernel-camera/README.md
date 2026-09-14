# Sargo lens lifecycle fix

This prepares kernel `7.1.2-0.pocketfed.sdm670.9` from the exact deployed `.8`
source, `38bef8725fa90dfb2be5a457eb75c656b1e45f0a`. It changes the
LC898219XI focus actuator driver, the derivative release number and the ARK
changelog. All existing audio, RMNET, Bluetooth, USB-C/PD and ath10k changes
are retained by ancestry.

The `.8` lens open callback restores controls before acquiring a runtime PM
reference, so it can write register `0x84` with the actuator powered down.
It also invokes the unlocked control setup helper without holding its mutex.
This is consistent with the live CCI timeout and `failed to set DAC: -110`
observed while querying the lens. Capture from the image sensor itself has
already worked on `.8`.

The patch acquires the open reference before the locking control setup call,
propagates both errors and drops that reference if setup fails. Each
successful open retains exactly one reference until close. Focus changes do
not acquire extra references. The device's existing one-second autosuspend
then applies after the final close, and reopening restores the cached focus.

Power-on now checks every I2C operation and unwinds its regulator enable on
failure. Transport errors are preserved, unexpected chip identity returns
`-ENODEV`, and the exhausted ten-read wakeup poll returns `-ETIMEDOUT`.

This deliberately keeps the actuator powered while its subdevice is open.
Turning it off between focus adjustments can reset focus during a capture.
An application or camera service which retains that file descriptor also
retains the power reference; the live acceptance check must confirm it closes
when the camera is released. The upstream per-control autosuspend change,
`2c8fbd253778713d03b5212d1f132fbc096c12f0`, is not included: it returns from
the focus branch before dropping the acquired reference, and its commit
message also warns about focus loss on autosuspend.

## Artifacts and validation

- `0001-media-i2c-lc898219xi-power-before-restoring-focus.patch`: exact source fix.
- `test-lc898219xi.py` and `lc898219xi-fixture.c`: compile the actual source
  functions against fault-injecting PM, regulator and I2C substitutes.
- `probe-lens.c`: native helper that opens the lens, exercises focus controls
  across timed holds, and closes it; it verifies control I/O and runtime-PM
  retention, not physical sharpness or calibrated focus.

The lifecycle test covers repeated focus changes, concurrent open references,
idle focus retention while open, final close, reopening before and after
autosuspend, regulator-enable failure, every power-on transfer failure, wrong
identity, wake timeout, and failed initial focus restoration. It uses
undefined-behavior traps and rejects the original `.8` source. This validates
driver control flow and reference accounting, not real kernel concurrency,
physical focus or power consumption.

The driver compiled with `W=1` for AArch64 against the same kernel tree with
arm64 defconfig plus the actuator module, and `checkpatch.pl --strict` reports
zero errors, warnings or checks for the patch. These are host build
validations; the driver has never been booted on the device.

## Test path

Current trials use the `tools/liveboot` kboop/fastboop workflow: build or
package a coherent kernel/DTB/modules candidate and boot an ephemeral USB-root
session. Public CI, COPR and installed-deployment acceptance are promotion
steps, not prerequisites for an ephemeral lens test.

To exercise the lifecycle regression against a prepared source tree, then
build the release and SRPM from it after the `.9` release commit:

```sh
python3 packages/kernel-camera/test-lc898219xi.py /path/to/linux

# From that kernel tree:
PATH=/usr/bin:/bin:$PATH make NO_CONFIGCHECKS=1 UPSTREAMBUILD_GIT_ONLY=0 \
    DIST=.fc46 DISTLOCALVERSION= dist-check-release dist-srpm
```
