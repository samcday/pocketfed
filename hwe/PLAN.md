# hwe: stock Fedora kernels plus an out-of-tree enablement delta

Tracker: [pocketfed #64](https://github.com/samcday/pocketfed/issues/64)
(evidence comment 2026-09-16). Decisions so far: this work lives here under
`hwe/`, targets rawhide, and fingerprint is deferred because its TEE frontend
depends on additions to the built-in Qualcomm SCM driver.

## Milestone A: unmodified rawhide kernel boots PocketFed on test-sargo

**Status 2026-09-17: reached.** multi-user (getty on UART, Enforcing, no failed
units) and graphical (Phosh greeter on the panel) both pass on the stock
7.3-rc3 kernel; see `hwe/evidence/2026-09-17-stock-rawhide-liveboot.md`.
Open: `msm` in the initrd triggers a TZ reset; touch needs the panel to come
up before rmi4 (same ordering issue).

Goal, deliberately conservative: `test-sargo` reaches `multi-user.target`
(getty on the UART, SELinux enforcing, liveboot handoff report) on the exact
rawhide `kernel-core` blob, its own `sdm670-google-sargo.dtb`, and its own
modules, with PocketFed userspace from a cached device OCI. Stretch: the same
with `graphical.target` and the greeter visible on the panel. No kmods, no
overlays, no image build, no flashing.

Known from the 2026-09-15/16 inspection:

| Item | State |
| --- | --- |
| Kernel under test | `kernel-7.3.0-0.rc3.260914g704340f1cd0d.32.fc46` (koji), source tag kernel-ark `kernel-7.3.0-0.rc3.704340f1cd0d.32` |
| RPMs | kernel-core, kernel-modules-core, kernel-modules, kernel-modules-extra, kernel-modules-internal, kernel-devel already downloaded to the session scratchpad |
| vmlinuz format | EFI zboot, zstd payload; `hwe/tools/hwe_common.py` (copied from the old `tools/liveboot/prepare-fixture.py`) decodes this to `Image.gz` |
| Modules | `.ko.xz`; kboop accepts `.ko.zst/.ko.xz/.ko.gz/.ko` |
| Early modules | `profiles/google-sargo-initrd.conf` lists `qcom_pmic_typec_smb2` and `qcom_fg`, which do not exist upstream; kboop only warns ("assuming built-in") |
| DTB | Fedora's blob has display, touch, USB, storage, PMIC basics; no remoteproc, wifi, audio, venus, camss, Type-C, fingerprint, haptics |
| Device | `test-sargo` serial `99NAY1AZG1`, UART `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_test-sargo-if00-port0` (ttyUSB1 on 2026-09-16). On 2026-09-16 17:50 AEST the phone was **not enumerated over USB** (only the DB410c `bc72e60` was in fastboot) |
| Fixture source | none exported yet under `out/liveboot/fixtures/`; cached complete device OCIs include `localhost/sargo-premouth:20260913` (post PR #59) and `localhost/sargo-fingerprint-pool:20260913` |

Expected to fail, and that is fine for A: modem/wifi/audio units, anything
Type-C/charger related that expects `qcom_smbx` + TCPM, feedbackd haptics.
Expected to work: console, storage (`sdhci_msm`), display (`msm` +
`panel_samsung_s6e3fa7`), touch (`rmi_i2c`), USB gadget root, battery basics.

### Steps

- **A1 bundle tool** (worker): `hwe/tools/fedora-kernel-bundle.py`. Input: a
  koji NVR or a directory of the five RPMs. Output: a kboop version-1 candidate
  bundle under `out/liveboot/candidates/<name>/` with `Image.gz` (decoded from
  zboot via `hwe_common.canonical_kernel`), `dtb/qcom/sdm670-google-sargo.dtb`,
  the complete module tree with depmod run for that release, `kernel.config`,
  `System.map`, and `provenance.json` (NEVRAs, RPM sha256, koji build id).
  Validate with the same checks `hwe_common.verify_kernel` /
  `hwe_common.verify_modules` apply (gzip stream, arm64 Image magic, release
  banner, module vermagic, completeness) rather than reimplementing them. Also
  emit `early-modules.txt` when `--early-modules` names the dracut conf: for each
  module, present / built-in / absent in this kernel. Add a host test next to
  the other `hwe/tools/test-*.py` style tests.
- **A2 fixture** (worker): `just liveboot-fixture` from
  `localhost/sargo-premouth:20260913` (resolve to the full image ID) into
  `out/liveboot/fixtures/sargo-premouth-20260913`, default overlay, `--reuse`.
  Host-only; no pull, no container execution.
- **A3 first boot** (supervisor, on the phone): `just liveboot-prepare` with the
  fixture plus the A1 bundle, then `just liveboot-boot` kept alive in a
  background process for the whole session. Read `result.json` and `uart.log`.
  Record: reached target, enforcing, failed units, oopses, probe deferrals.
  End with `just liveboot-sysrq --key reboot`.
- **A4 graphical** (worker prepares, supervisor boots): derived profile
  `out/hwe/liveboot/google-sargo-stock-graphical.json` (same as `google-sargo.json`
  with `systemd.unit=graphical.target`), second run, Sam confirms the greeter.
- **A5 evidence** (worker): `hwe/evidence/<date>-stock-rawhide-liveboot.md`
  with the compact facts (hashes, release, target reached, failed-unit list,
  timings) and links to run directories; no raw logs in git. Draft PR from this
  branch.

## Milestone B: the ostree + ABLX image path

Same kernel, but composed the production way: a `devices/google-sargo`
Containerfile variant that installs Fedora's `kernel` instead of the COPR one,
`pocketfed-verify-kernel` accepting the rawhide release pattern, the installed
`dracut.conf` tolerant of the two downstream-only early modules, local arm64
image build, fixture export from that image, liveboot with the image's own
kernel (no `--kernel-bundle`). Then, with Sam's nod, `just fastboot` images
onto test-sargo to prove the installed aboot path.

## Milestone C: first enablement package

Only after A and B. Candidates, easiest first: haptics (`drv2624` new driver +
one DT node), then the `core` overlay (remoteproc/smp2p/wifi) which is the big
functional win but the largest overlay. The DTB symbol-injection tool and the
per-kmod packaging described in the #64 comment land here.

## Working agreements

- The hwe tools are self-contained: shared kernel/bundle helpers live in
  `hwe/tools/hwe_common.py` (with their original source commit noted in its
  header). Nothing under `hwe/` imports or depends on `tools/liveboot`, which no
  longer exists on `origin/main`.
- Branch `claude/hwe-stock-kernel` in the `pocketfed-hwe` worktree; the shared
  `pocketfed` checkout stays untouched. Workers write only under `hwe/` and
  `out/`.
- Workers: DeepSeek V4.1 Flash (high) via opencode-go, one bounded brief per
  step with an explicit report path; supervisor verifies diffs and evidence.
- Phone sessions are run by the supervisor, never by a worker whose tool call
  can time out and kill USB-root hosting.
