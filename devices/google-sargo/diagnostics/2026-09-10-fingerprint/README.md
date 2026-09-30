# Sargo fingerprint feasibility — 10 September 2026

Investigation for [sam-sargo #11](https://github.com/samcday/sam-sargo/issues/11).
Read-only inspection over the tailnet while the phone was being carried.

**Result:** the phone has a responding Qualcomm QSEE firmware interface and
retained stock FPC trusted-app/HAL files. PocketFed currently lacks an exposed
sensor-control path and the legacy QSEECOM userspace application workflow needed
to use them. There is credible reusable implementation work, but no working
native Sargo fingerprint path was identified. Installing fprintd or removing one
kernel allowlist check would not fill the missing layers.

The essential interface gap is the stopping point for this feasibility pass.
No sensor reset, pin change, module load, TA command, enrollment, service restart,
package installation, authentication change, mount, partition write, or reboot
was performed. No biometric stores were inspected. Proprietary binaries stayed
on the device; the recorded firmware evidence is filenames, lengths, hashes and
ELF metadata.

## Measured baseline

[Live inventory](live-inventory.json) was captured at 17:40 AEST;
[vendor inventory](vendor-inventory.json) was finalized at approximately 17:44 AEST.

| Layer | Observation | Meaning / limit |
| --- | --- | --- |
| Device | `Google Pixel 3a`; `google,sargo`, `qcom,sdm670` | Live DT identity |
| Kernel | `7.1.2-0.pocketfed.sdm670.8.fc46.aarch64` | This is the running baseline, not the prepared camera `.9` build |
| QSEE | Boot log reports QSEECOM version `0x1400000` | A version query reached secure firmware; fingerprint commands remain untested |
| QSEECOM registration | `untested machine, skipping` | Sargo is excluded by the current kernel's machine allowlist |
| TEE configuration | `QCOM_SCM=y`, `QCOM_QSEECOM=y`, `QCOM_QSEECOM_UEFISECAPP=y`, `TEE=m`, `QCOMTEE=m`; qcomtee module installed | Build capability does not establish the required transport |
| Exposed interfaces | No matching `/dev/tee*`, `/dev/qsee*`, fingerprint/FPC nodes, or matching platform/TEE devices | Current registration state; not proof hardware cannot support them |
| Sensor description | No FPC/fingerprint DT node; only `qseecom@9e400000`, a 20 MiB reserved region | Reserved memory alone does not implement a fingerprint interface |
| SPI | Only `spi0.0`, bound to `rt5514` audio | Not a fingerprint sensor; its absence from Linux SPI is consistent with the stock platform-driver design |
| Linux pin ownership | TLMM GPIO121 and GPIO134 report `UNCLAIMED` | No reported Linux pinctrl consumer; this does not measure voltage, reset state, or secure-world ownership |
| Native userspace | No matching libfprint/fprintd/QSEE supplicant packages or services; no fingerprint references in the three inspected PAM files | No packaged native path identified; custom binaries were not exhaustively ruled out |
| Firmware extraction | Installed Sargo blob-wrangler configuration omits the fingerprint TA; none found in the searched native firmware directories | Stock files are available separately in retained Android vendor |

## Stock firmware is available

Read-only `debugfs` inspection used the already-existing `/dev/mapper/vendor_b`.
That filesystem currently identifies itself as Android 12
`SP2A.220505.008/8782922`, security patch `2022-05-05`. Use this identity for this
investigation: it differs from older slot-B notes in the workspace.

Present in that filesystem:

- `/firmware/fpctzappfingerprint.mbn`, `.mdt`, and `.b00` through `.b07`.
- `/firmware/cmnlib*` and `cmnlib64*`. Presence does not prove which libraries
  this TA requires or which are already resident in QSEE.
- `/bin/hw/android.hardware.biometrics.fingerprint@2.1-service.fpc`,
  `/lib64/libQSEEComAPI.so`, `/lib64/com.fingerprints.extension@1.0.so`,
  `/bin/qseecomd`, and the FPC init configuration/helper.

The FPC service's ELF dependency table directly names `libQSEEComAPI.so`, the
fingerprint 2.1/2.2 HIDL libraries and `com.fingerprints.extension@1.0.so`.
These are Android components, not an operational native Fedora stack. The
absence of the separately guessed `fingerprint.sdm670.so` path is not an absent
HAL: the service above exists.

The TA `.mbn` is **691,540 bytes, ELF64/AArch64**, SHA-256
`e947fd8b081b47be9bd75c87cbd95a79fd8955b9d3310631680ca47fd76997e8`.
Its ELF header reports **zero section headers**; the `.mdt` does too. The service,
extension library and QSEE API library have dynamic symbol tables, but no
ordinary `.symtab` was found in those inspected ELF sections. Do not assume
the unstripped-TA shortcut reported for another Pixel is available here.
No disassembly or protocol inference from the executable contents was attempted.

Files on disk and plausible ELF headers do not establish signature acceptance,
successful TA loading, an exact command ABI, or functioning hardware.

## Hardware and interface architecture

The stock [Sargo/Bonito fingerprint DT](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/arch/arm64/boot/dts/google/sdm670-b4s4-fingerprint.dtsi)
declares a platform node compatible with `fpc,fpc1020`, **GPIO121 for IRQ** and
**GPIO134 for reset**. Its reset states drive low/high; IRQ has a pull-down.
The [stock driver](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/drivers/input/misc/fpc_fingerprint/fpc1020_platform_tee.c),
selected by `CONFIG_FPC_FINGERPRINT`, supplies electrical control and a polled
sysfs IRQ. It does not send sensor commands or implement biometric matching.

The stock compatible establishes the driver family, **not a measured sensor
part/revision**. The exact physical SPI controller and pin routing were not
established. The platform node, Android QSEE dependencies, and a
[public Pixel 3a Android boot trace](https://gist.github.com/tanyeun/64a7a54410b14195aac60c8bca8285ab)
loading the same TA support the secure-world architecture; they do not justify
assigning an arbitrary Linux SPI bus or copying another phone's pins.

The running kernel's corresponding source release is
[38bef8725fa90](https://github.com/samcday/linux/commit/38bef8725fa90dfb2be5a457eb75c656b1e45f0a).
Its [SCM implementation](https://github.com/samcday/linux/blob/38bef8725fa90dfb2be5a457eb75c656b1e45f0a/drivers/firmware/qcom/qcom_scm.c)
uses a QSEECOM machine allowlist because re-entrant calls are not supported by
that implementation. The [QSEECOM client table](https://github.com/samcday/linux/blob/38bef8725fa90dfb2be5a457eb75c656b1e45f0a/drivers/firmware/qcom/qcom_qseecom.c)
only contains the UEFI secure app and assumes apps are already loaded.
Allowlisting Sargo would not create Android's `/dev/qseecom`, a fingerprint app
loader, or the required listener services.

Separately, [mainline qcomtee](https://docs.kernel.org/tee/qtee.html) implements the
object-based **smcinvoke** protocol. It is not a replacement for the legacy
QSEECOM app protocol solely because both involve Qualcomm secure firmware.
The current source probes smcinvoke before registering its platform device;
there is no registered qcomtee device here. The precise reason for that absence
was not measured, and forcibly loading its module was not part of this pass.

## Reusable work

| Implementation | What it contributes | Compatibility limit |
| --- | --- | --- |
| [Wrobelda QSEECOM work](https://github.com/wrobelda/goodix-fp-spi-linux), [kernel transport](https://github.com/wrobelda/linux/tree/qcom-qseecom-tee), [qsee-supplicant](https://github.com/wrobelda/qsee-supplicant) | Legacy app loading, shared buffers and listeners through the Linux TEE subsystem; author reports enrollment/matching/persistence on SM8250 | Out of tree; SCM/MDT changes needed. Reference device uses Goodix `gfenu`, so its commands and sensor driver do not establish FPC compatibility |
| [Pixel 3 / blueline FPC investigation](https://forge.caseytunturi.com/Fimeg/SouveraineOS/src/branch/public/docs/tasks/44-fingerprint-fpc1020.md) | Author reports signed `fpctzappfingerprint` loading and sensor init/arm commands; a closer protocol lead | No complete biometric enrollment/match demonstrated by that note; linked detailed Pixel3Arch protocol source was not retrieved. Its temporary IRQ-based PAM bridge is not biometric verification |
| [Fairphone 6 fingerprintd](https://forgejo.catcrafts.net/Catcrafts/fingerprintd) | Native daemon with reported enrollment and wrong-finger rejection; useful lifecycle/testing reference | Focaltech `focal64` on newer QTEE, not Sargo's FPC/legacy QSEECOM path |
| Stock GPLv2 FPC driver and board DT above | Exact Sargo reset/IRQ reference | Requires a mainline-compatible implementation and review; provides no TA protocol |

The blueline task note was retrieved through its
[raw Forge endpoint](https://forge.caseytunturi.com/Fimeg/SouveraineOS/raw/branch/public/docs/tasks/44-fingerprint-fpc1020.md).
Its claims are source leads, not independently repeated Sargo results. An older
article URL was unavailable. No ready-to-install native Sargo FPC stack was found
in this bounded search; this is not a claim that none can exist.

## Smallest next experiment and stopping gates

**Next work can remain off-device:** map the exact stock FPC service's
QSEECom load/send calls, buffer sizes, modified-command address fixups and
initial command sequence. Compare these with the blueline protocol lead and
the [legacy transport's interfaces](https://github.com/wrobelda/goodix-fp-spi-linux/blob/master/docs/01-kernel-tee-driver.md).
Use the captured hashes to select this firmware version. The ordinary full
symbol-table shortcut is unavailable in the inspected TA, so obtain the public
protocol details or analyze the exact HAL locally before choosing command bytes.
Document required listeners, secure storage, common libraries and any
Gatekeeper/authentication-token dependence; these remain unresolved for Sargo.

The first later **device** experiment should use a recoverable **COPR-built**
kernel trial, with the user back near USB/recovery access:

1. Add only the reviewed Sargo control/IRQ description and necessary legacy
   QSEECOM transport support. Establish the intended TEE implementation identity
   and basic API discovery; do not identify the backend by `/dev/tee0` alone.
2. Attempt loading the device's own TA, then one understood non-enrollment
   initialization command. Record app-load result, required listener activity,
   IRQ before/after, clean close, and any system-wide side effects. Missing
   required listener/library or unsupported ABI is a concrete stop condition.
3. Only after initialization works, prove intentional touch detection, then
   actual enrollment and enrolled-finger match **with wrong-finger rejection**.
   A touch interrupt must never count as authentication.
4. Establish persistence, cancellation, retry limits, suspend/resume and reboot
   behavior before integrating a native FPC client with libfprint/fprintd/PAM.
   Keep PIN fallback. Unlocking an existing Phosh session and unlocking an
   inactive encrypted homed home are distinct milestones: a match result alone
   does not provide the home decryption secret.

The transport reference documents reset and stuck-listener failure modes, so
even app loading is a functional trial rather than another read-only query.
This pass deliberately ends before that boundary. No trial was built or staged.

## Reproducing the evidence

The collectors are sent over stdin and execute no local file installation:

```sh
ssh root@sam-sargo python3 - < collect.py > live-inventory.json
# First verify vendor_b is still the intended existing stock mapping.
ssh root@sam-sargo python3 - < collect-vendor.py > vendor-inventory.json
```

`collect.py` reads selected kernel/sysfs/package/configuration data.
`collect-vendor.py` deliberately fixes the inspected `vendor_b` mapping and uses
`debugfs` without `-w`; it neither creates mappings nor mounts anything. Its
binary bytes remain in the remote Python process and only metadata is emitted.
The missing guessed HAL path is recorded explicitly instead of treated as an
absent fingerprint service. Each command is bounded by a timeout. Inspection
scripts and JSON were checked locally; no hardware or authentication test was
run, and unrelated workspace changes were left alone.
