# Sargo on stock Fedora kernels: working plan (2026-09-15)

Continues [pocketfed #64](https://github.com/samcday/pocketfed/issues/64) (Codex, 14 Sep).
This document adds the evidence gathered today, answers the DTB-overlay question,
and turns the milestones into delegable task briefs.

## 1. Evidence gathered today

### Fedora ships the board DTB, without overlay symbols

| Fact | Value |
| --- | --- |
| Rawhide build inspected | `kernel-core-7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64` (koji) |
| Exact source | kernel-ark tag `kernel-7.3.0-0.rc3.704340f1cd0d.32` (fetched into a local worktree) |
| `dtb/qcom/sdm670-google-sargo.dtb` | present, 50,824 bytes, 134 nodes carry a `phandle`, **no `__symbols__`** |
| Downstream `.11` DTB for comparison | 104,120 bytes, 37 `status = "okay"` nodes vs 18 in Fedora's |
| Why no symbols | `kernel.spec` runs plain `make dtbs`; only boards listed with `-dtbs := base.dtb x.dtbo` in `arch/arm64/boot/dts/qcom/Makefile` get `-@`, and sargo is not one |
| `python3-libfdt` | installed on this host (pylibfdt available); `dtc 1.8.1`, `fdtoverlay`, `fdtput` present |

Nodes present downstream but absent from Fedora's blob:

- `/soc@0`: adsp/cdsp/mss remoteprocs, `wifi@18800000`, `ipa@1e40000`, `video-codec@aa00000` (venus), `audio-codec@62ec0000` (lpass), both `lmh@`, `mailbox@17990000`, `power-management@c300000` (aoss qmp), both `reset-controller@`, `syscon@1f60000` (tcsr), two `thermal-sensor@`, `clock-controller@ab00000`.
- root: `sound`, `smp2p-{mpss,lpass,cdsp}`, `modemsmem`, `fingerprint`, `opp-table-qup`, `regulator-ext-5v-boost`, three rear-camera regulators, `masked-devices` + `__symbols__` (the stock-bootloader DTBO mask).

So a stock Fedora kernel boots sargo with display, touch, USB, storage, PMIC basics. No modem, wifi, audio, video, camera, fingerprint, Type-C, haptics, thermal limits.

### Fedora aarch64 config is friendly

Modular (`=m`) and therefore usable or replaceable from `updates/`: `QCOM_Q6V5_PAS`, `QCOM_Q6V5_MSS`, `QCOM_MDT_LOADER`, `QCOM_SMEM`, `RPMSG_QCOM_GLINK*`, `QCOM_APR`, `QCOM_PDR_HELPERS`, `QCOM_RMTFS_MEM`, `QCOM_IPA`, `ATH10K_SNOC`, all `SND_SOC_QDSP6_*`, `SND_SOC_MSM8916_WCD_{ANALOG,DIGITAL}`, `SND_SOC_RT5514`, `VIDEO_QCOM_CAMSS`, `VIDEO_QCOM_VENUS`, `VIDEO_IMX355`, `TYPEC_TCPM`, `TYPEC_QCOM_PMIC`, `CHARGER_QCOM_SMB2`, `QCOM_LMH`, `QCOM_SPMI_ADC_TM5`, `QCOM_GPI_DMA`, `RMI4_*`, `TEE`.

Not built by Fedora (pure polyfill, no conflict): `SND_SOC_SM8250` (sargo's sound card driver), `SND_SOC_CS35L36`.

Built-in (cannot be replaced by a module): `QCOM_SCM`, `QCOM_QSEECOM`, `QCOM_TZMEM` (generic mode), `SERIAL_QCOM_GENI`, `QCOM_RPMH`, `QCOM_COMMAND_DB`.

Module loading: `MODVERSIONS` off (vermagic match only), `MODULE_SIG=y` without `SIG_FORCE` (unsigned modules load with a taint).

### The downstream delta, bucketed

138 files, +25.8k lines vs Linux 7.1.2 (excluding `redhat/`). Grouped by treatment on a stock kernel:

| Bucket | Content | Treatment |
| --- | --- | --- |
| DT only | `sdm670.dtsi` +1.4k, `sdm670-google-common.dtsi` +0.9k, `pm660*.dtsi`, sargo `fingerprint` node | overlays (see §2) |
| New drivers Fedora lacks entirely | `fpc1020`, `qseecom` TEE frontend, `drv2624`, `qcom-spmi-haptics`, `qcom_fg`, `imx363`, `lc898219xi`, `modemsmem`, `panel-samsung-sofef00-bonito`, q6voice suite (`q6mvm/q6cvs/q6cvp/q6voice-dai`), SMB2 Type-C (`qcom_pmic_typec_smb2`, already exists out of tree), `sm8250` sound card, `cs35l36` | external kmods, no conflict |
| Patched modular drivers | `q6afe`, `q6afe-dai`, `q6routing`, `q6core`, `msm8916-wcd-analog` (+144), `qcom_smbx` (+882), `ath10k` htt_rx fix, `lmh` (+54), `adc-tm5` (+7), `venus` (tiny), `qcom_glink_native` (+31, "VIBES" fix), `dispcc-sdm845` (+1), `edt-ft5x06` (+2), `tcpm` (+5), `rt5514`, `mdt_loader` (+234, fingerprint ELF helpers) | replacement kmods in `updates/`; each needs a probe-ownership check |
| Compatible-only driver patches | `qcom_q6v5_pas` (+2 lines), `qcom_q6v5_mss` (+1), `ipa_main` (+4): they only add `qcom,sdm670-*` match entries pointing at sdm845 data | **avoid entirely**: write the overlay with the sdm845 compatible the stock module already matches (`"qcom,sdm670-adsp-pas", "qcom,sdm845-adsp-pas"` style fallback where the binding allows it, or plain sdm845 compatible otherwise) |
| Built-in changes | `qcom_scm.c` +496 (QSEECOM app load/shutdown, listeners, service load; creates the `qcom_qseecom_tee` platform device) | residual kernel patch or upstreaming; the one true blocker |
| Boot-time | `head.S`/`image.h` TEXT_OFFSET=0x80000 | **not needed**: abl-exorcist masquerades text_offset already |
| Userspace-fixable | `soc-core.c` +1 (card `long_name` for UCM lookup) | UCM config/symlink instead of patching core |
| Config only | `redhat/configs` additions (RMNET, sound cards, ...) | become `compat/required-configs` checks per kmod; anything Fedora leaves off becomes a polyfill kmod |

## 2. The DTB question, answered

The concern: Fedora's blob has no `__symbols__`, so a `.dtso` that references `&tlmm`
or `&vreg_l19a_3p3` cannot be applied by `fdtoverlay`. Path-targeted fragments
(what `sdm845-fedora-hwe` does) only cover nodes with no external phandle references.

Proposed answer: **reconstitute the symbols from the exact source, with an equivalence gate.**

1. Every Fedora kernel build corresponds to a public kernel-ark tag. Compile
   `sdm670-google-sargo.dts` from that tag with `dtc -@` (cpp + dtc, no full kernel build).
2. Gate: `dtc -I dtb -O dts` both blobs, strip `__symbols__` and `phandle` lines, require
   byte-identical output. If it differs, the contract is broken and composition refuses.
3. Inject into Fedora's literal blob: add `/__symbols__` (label to path) and a `phandle`
   to every labelled node that lacks one (dtc without `-@` only numbers referenced nodes;
   `fdtoverlay` fails on a target with no phandle). Preserve Fedora's existing numbering.
   pylibfdt does this in ~50 lines; `fdtput` can do it from shell.
4. `fdtoverlay -i sargo.symbolised.dtb -o sargo.final.dtb core.dtbo fingerprint.dtbo ...`
   at image-composition time (the Containerfile `initrd` stage already copies the blob
   into the boot image; this replaces that one `install` line). Record base hash, tag,
   overlay list and output hash in a sidecar.

This keeps issue #64's "distro DTB as versioned input contract" literally: the base
bytes are Fedora's, the symbols are derived, and the gate proves they belong together.
Full-DTB generation stays the fallback. A longer-term nicety is asking Fedora to pass
`DTC_FLAGS=-@` in `kernel.spec`; not required.

Caveats to carry into the overlays:

- Overlays can only add or set; they cannot delete. The downstream tree does
  `/delete-node/` on reserved-memory regions to re-lay them out. Check whether the
  Fedora blob's reserved-memory layout is already the mainline one we need.
- The stock ABL applies the `dtbo` partition to whatever DTB it boots. Downstream masks
  it with `sdm670-google-common-dtbo-mask.dtsi`; mainline dropped that. Confirm how
  abl-exorcist / `pocketfed-aboot-finalize` handle the dtbo partition before assuming
  Fedora's unmasked blob is safe (the same question applies to the composed blob).

## 3. Fingerprint on a stock kernel

| Piece | Verdict |
| --- | --- |
| `fpc1020.ko` (354 lines, `google,sargo-fingerprint` OF match, GPIO/IRQ/wakeup only) | external kmod, first candidate |
| `/fingerprint` node + `tlmm` pinctrl state | `fingerprint.dtso`; external ref is only `&tlmm`, which already has a phandle in Fedora's blob |
| `qseecom` TEE frontend (1,951 lines) | already modular; needs `TEE=m` (ok), `QCOM_MDT_LOADER` helpers (`qcom_mdt_get_image_size/read_image`: move under private names into the module), `qcom_tzmem_*` (exported upstream), `qcom_scm_qseecom_app_get_id/app_send` (exported upstream), and **five new SCM exports plus the `qcom_qseecom_tee` platform device** (not upstream) |
| `qcom_scm.c` additions | residual patch. Options: (a) interim "Fedora ARK + one patch" kernel stream, tiny delta, still needs COPR; (b) raw `__arm_smccc_smc` from the module (exported) — rejected, bypasses `qcom_scm_lock`/listener serialisation; (c) upstream the app-manager/listener interface as part of the qseecom TEE submission |

So fingerprint splits into "external now" (companion driver, overlay, TEE module body)
and "kernel patch until upstreamed" (SCM interface). That matches the Codex assessment.

## 4. Proposed shape

Single source repo `sdm670-hwe` (name open), several RPMs, building on
`sdm845-fedora-hwe` and `qcom-pmic-typec-smb2`:

```
sdm670-hwe/
  dt/
    tools/dtb-symbolise, compose-dtb   # equivalence gate + symbol injection + fdtoverlay
    overlays/{core,fingerprint,haptics,audio,camera,typec}.dtso
    tests/                             # per-Fedora-build fixture: base hash, tag, expected result
  kmods/<name>/                        # external Kbuild dirs; provenance = upstream commit + patches
    Kbuild, compat/required-configs, scripts/check-exports (reuse typec repo's)
  packaging/fedora/
    sdm670-hwe-dt.spec                 # .dtbo files + compose-dtb
    sdm670-hwe-kmod-<name>.spec        # kmodtool/akmods, one per feature group
    sdm670-hwe.spec                    # metapackage selecting the tested set
  .copr/ + CI                          # build against rawhide aarch64 kernel-devel in an arm64 container (qemu-user works here)
```

Feature groups (each = kmods + overlay + required-configs): `core` (remoteproc, smp2p,
rmtfs, glink fix, ipa, wifi, thermal/lmh, qup/opp), `audio`, `fingerprint`, `haptics`,
`camera`, `typec`, `power` (fg, smbx), `video`.

PocketFed integration: Containerfile installs Fedora `kernel` + `sdm670-hwe*` from COPR;
the `initrd` stage runs `compose-dtb`; `pocketfed-verify-kernel` gains an overlay check.
On-device akmods stays optional.

## 5. Delegable task briefs (DeepSeek V4.1 Flash via opencode)

M0 spikes, independent, run in parallel:

- **S1 DTB gate + symbolise + fingerprint overlay.** Inputs: Fedora blob (extracted),
  kernel-ark worktree, downstream `fingerprint` node. Deliver: `dtb-symbolise` (pylibfdt),
  equivalence report, `fingerprint.dtso`, composed blob, `dtc -I dtb -O dts` diff showing
  exactly the added nodes. Also report the reserved-memory and dtbo-mask caveats concretely.
- **S2 `fpc1020` external build.** Copy driver into a Kbuild dir, build against rawhide
  aarch64 `kernel-devel` in an arm64 container, run an export audit against
  `Module.symvers`, report vermagic. Reuse `qcom-pmic-typec-smb2/scripts/check-exports.sh`.
- **S3 Inventory table.** For every non-`redhat/` file in the delta: Kconfig symbol,
  Fedora 7.3-rc3 config state, bucket per §1, and for DT files the nodes they add.
  Output: markdown table for #64. Include the sdm670-linux-patches list so upstream
  status per patch is visible.

M1 (after S1–S3): repo skeleton, `core` overlay + polyfills, first liveboot of a stock
rawhide kernel with composed DTB on the test device. Gate: modem, wifi and audio
come up with zero kernel patches.

M2: fingerprint group + decision on the SCM residual patch. M3: switch pocketfed sargo
Containerfile; retire COPR kernel.

## 6. Decisions needed

1. Repo name and home: `samcday/sdm670-hwe` (matches #64 naming), or fold into
   a multi-platform `pocketfed-hwe` alongside the sdm845 kmods?
2. Target Fedora stream: rawhide, as pocketfed does today?
3. Post this document (or §1–§3) as a comment on #64?
4. Fingerprint SCM interface: accept an interim minimal-patch kernel stream, or go
   straight for upstreaming and keep fingerprint on the current COPR kernel meanwhile?
5. Start S1–S3 now via opencode (DeepSeek V4.1 Flash, high)?
