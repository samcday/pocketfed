Part of #3.

**Status / owner:** Initial read-only feasibility investigation completed by the fingerprint investigation task on **10 September 2026**. Implementation remains exploratory; no enrollment, biometric verification, or unlock support has been demonstrated. No functional trial is running or staged.

## Current finding

**A plausible FPC/QSEE path exists, with concrete missing Linux interfaces.** The stock trusted app and Android HAL are present on this phone. PocketFed does not currently expose the sensor's reset/IRQ control or a legacy QSEECOM userspace application workflow. Installing fprintd or removing the QSEECOM machine allowlist check alone would not provide fingerprint support.

The missing application transport/loader/listeners are the essential-interface blocker and stopping point for this feasibility pass. The phone was inspected over the tailnet while being carried; no reset, pin change, module load, TA invocation, package/service/authentication change, mount, partition write or reboot was performed. No biometric stores were read, and proprietary binaries stayed on the phone.

## Device evidence — 10 September, 17:40–17:44 AEST

| Layer | Observed state |
| --- | --- |
| Baseline | Pixel 3a, `google,sargo` / `qcom,sdm670`, kernel `7.1.2-0.pocketfed.sdm670.8.fc46.aarch64` |
| Secure firmware | Kernel successfully queries QSEECOM version `0x1400000`, then logs `untested machine, skipping` |
| Native interfaces | No matching `/dev/tee*`, `/dev/qsee*`, FPC/fingerprint nodes or corresponding platform/TEE device; no fingerprint DT node |
| Sensor pins | Stock Android DT assigns IRQ GPIO121 and reset GPIO134; both report `UNCLAIMED` in current Linux pinctrl. This does not measure electrical state or secure ownership |
| Native userspace | No matching libfprint/fprintd/QSEE supplicant packages or services identified; inspected PAM files contain no fingerprint references |
| Stock vendor | Existing `vendor_b` identifies `SP2A.220505.008/8782922`, security patch 2022-05-05; contains `fpctzappfingerprint.{mbn,mdt,b00..b07}`, common-library files, FPC service, `libQSEEComAPI.so` and `qseecomd` |
| Extraction | Installed blob-wrangler config omits the fingerprint trusted app; no matching TA found in the searched native firmware directories |

`fpctzappfingerprint.mbn` is 691,540 bytes, ELF64/AArch64, SHA-256 `e947fd8b081b47be9bd75c87cbd95a79fd8955b9d3310631680ca47fd76997e8`. Its ELF header has zero section headers, so an ordinary full-symbol-table shortcut is not established for this image. The stock FPC service directly depends on `libQSEEComAPI.so`, fingerprint HIDL 2.1/2.2 and `com.fingerprints.extension@1.0.so`. File presence is not proof of accepted TA signatures, successful loading or a working sensor.

## Architecture and existing implementations

- The [stock board DT](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/arch/arm64/boot/dts/google/sdm670-b4s4-fingerprint.dtsi) and [GPLv2 FPC platform driver](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/drivers/input/misc/fpc_fingerprint/fpc1020_platform_tee.c) provide a concrete reset/IRQ reference. The driver sends no sensor commands. `fpc,fpc1020` identifies the driver family; the fitted silicon revision and physical secure SPI controller remain unverified. The only live Linux SPI device is RT5514 audio.
- Current [QSEECOM kernel clients](https://github.com/samcday/linux/blob/38bef8725fa90dfb2be5a457eb75c656b1e45f0a/drivers/firmware/qcom/qcom_qseecom.c) only cover an already-loaded UEFI app. The [SCM allowlist](https://github.com/samcday/linux/blob/38bef8725fa90dfb2be5a457eb75c656b1e45f0a/drivers/firmware/qcom/qcom_scm.c) is not the only gap. Installed `CONFIG_QCOMTEE=m` is also not the answer by itself: [qcomtee uses the separate smcinvoke object protocol](https://docs.kernel.org/tee/qtee.html).
- [Wrobelda's legacy QSEECOM implementation](https://github.com/wrobelda/goodix-fp-spi-linux), [kernel branch](https://github.com/wrobelda/linux/tree/qcom-qseecom-tee), and [qsee-supplicant](https://github.com/wrobelda/qsee-supplicant) are useful transport/loader/listener candidates. The author reports complete fingerprint operation on an SM8250 Goodix device. The kernel work is out of tree; its Goodix protocol and hardware driver do not establish FPC compatibility.
- [Current blueline FPC notes](https://forge.caseytunturi.com/Fimeg/SouveraineOS/src/branch/public/docs/tasks/44-fingerprint-fpc1020.md) report loading the same TA name and initializing/arming the sensor. This is a close protocol lead, not demonstrated Sargo enrollment/matching. The detailed linked Pixel3Arch protocol source was not retrieved. Its temporary raw-IRQ PAM bridge must not be treated as biometric authentication. Sargo's inspected TA lacks the ordinary section table behind that report's unstripped-TA shortcut.
- [Fairphone 6 fingerprintd](https://forgejo.catcrafts.net/Catcrafts/fingerprintd) offers another native lifecycle/testing reference, but uses Focaltech/newer QTEE and is not a Sargo driver.

## Next bounded work

- [x] Inspect live sensor/TEE registration and packages read-only.
- [x] Identify stock control wiring and inspect retained TA/HAL metadata without exporting proprietary bytes.
- [x] Find reusable transport and FPC-specific research; distinguish author reports from Sargo measurements.
- [ ] Map the exact FPC service's QSEECom load/send calls, buffer layout/address fixups and initial commands; compare with the blueline lead. Resolve required listeners, common libraries, storage and authentication-token dependencies. Keep this static investigation separate from live commands.
- [ ] Review/adapt the legacy transport and Sargo control/IRQ support into a **COPR-built**, recoverable kernel trial when local USB/recovery access is available. First prove transport discovery, loading this phone's own TA, one understood non-enrollment initialization command and clean close. Stop at a missing required interface/component or unsupported ABI.
- [ ] Only then prove touch detection, enrollment, enrolled-finger match **and wrong-finger rejection**, persistence and lifecycle behavior. A touch IRQ is not a match. Integrate with libfprint/fprintd/PAM only after that evidence exists.

PIN fallback must remain available. Lock-screen authentication and unlocking an inactive encrypted homed home are distinct integration questions; a biometric match alone does not supply a home decryption secret. Keep reusable support in upstreams/PocketFed, not a private authentication fork. Do not publish biometric templates, secrets or proprietary artifacts. Kernel changes must go through COPR.

Detailed report, read-only collectors and JSON evidence are saved locally in PocketFed at `devices/google-sargo/diagnostics/2026-09-10-fingerprint/`. They are not yet committed or uploaded; the essential findings and public sources are recorded above.
