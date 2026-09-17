# Brief A1b: build the three Fedora-disabled SDM670 drivers as external kmods

Context: `out/liveboot/candidates/stock-rawhide-73rc3-01/early-modules.txt`
shows `pinctrl_sdm670`, `qnoc_sdm670` and `panel_samsung_s6e3fa7` absent from
Fedora's kernel. `kernel.config` confirms `PINCTRL_SDM670`,
`INTERCONNECT_QCOM_SDM670` and `DRM_PANEL_SAMSUNG_S6E3FA7` are not set. All
three are unmodified upstream tristate drivers, so we build them out of tree
from the exact source of this Fedora build and add them to the bundle.

Work only in `/var/home/sam/src/pocketfed-hwe` (branch `claude/hwe-stock-kernel`).
Write only under `hwe/` and `out/`. No commits, no pushes, no phone access.
Podman is allowed for this brief, only as described below.

Inputs already present:

- Exact source tree: `out/hwe/linux-ark-7.3rc3/` (git worktree at kernel-ark
  tag `kernel-7.3.0-0.rc3.704340f1cd0d.32`, the source of the RPMs). Read only.
- `out/hwe/rpms/kernel-devel-7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64.rpm`.
- The bundle from A1 at `out/liveboot/candidates/stock-rawhide-73rc3-01/`.
- Prior art for external Kbuild, config and export checks:
  `/var/home/sam/src/sdm845-fedora-hwe/` (read only) and the scripts described
  in `hwe/design-notes-2026-09-15.md`.

## Deliverables

1. `hwe/kmods/sdm670-early/` containing:
   - `src/` with verbatim copies of `drivers/pinctrl/qcom/pinctrl-sdm670.c`,
     `drivers/interconnect/qcom/sdm670.c`,
     `drivers/gpu/drm/panel/panel-samsung-s6e3fa7.c` and the private headers
     they include (`pinctrl-msm.h`, `icc-rpmh.h`, `bcm-voter.h`, plus anything
     those pull in that is not under `include/`). Copy from the worktree; do
     not edit the driver sources. Record each copied file's source path and git
     blob id in `PROVENANCE.md`.
   - `Kbuild` producing `pinctrl-sdm670.ko`, `qnoc-sdm670.ko` and
     `panel-samsung-s6e3fa7.ko` (same module names as in-tree), with
     `ccflags-y` for the private headers.
   - `Makefile` with the usual `KDIR ?=` wrapper (`make -C $(KDIR) M=$(PWD) modules`).
   - `required-configs`: the Kconfig symbols the modules rely on being =y or =m
     in the target (`PINCTRL_MSM`, `INTERCONNECT_QCOM_RPMH`,
     `INTERCONNECT_QCOM_BCM_VOTER`, `DRM_MIPI_DSI`, `DRM_PANEL` and whatever
     else you find), and a small `check-config.sh` that verifies them against a
     kernel `.config`.
   - `check-exports.sh`: for a built `.ko`, list every undefined symbol
     (`nm -u` on the decompressed module) and fail if any is missing from the
     target's `Module.symvers`. Model it on the checks described in the design
     notes; keep it standalone POSIX shell.
2. `hwe/tools/build-kmods-arm64.sh`: builds a kmod directory against a
   kernel-devel RPM inside an arm64 rawhide container (this host runs arm64
   containers under emulation; the compile will be slow but works):
   `podman run --rm --arch arm64 -v <checkout>:/work registry.fedoraproject.org/fedora:rawhide`,
   inside: `dnf install -y /work/out/hwe/rpms/kernel-devel-*.rpm gcc make
   elfutils-libelf-devel kmod xz flex bison openssl-devel diffutils`, then
   `make -C /usr/src/kernels/<release> M=/work/hwe/kmods/sdm670-early modules`.
   Never mount or write anything outside the checkout. Cache the prepared
   container as a local image tag (`localhost/pocketfed-hwe-kbuild:73rc3`) so
   reruns skip the dnf step; document the tag in the script header.
3. `hwe/tools/bundle-add-kmods.py`: copies built `.ko` files into an existing
   candidate bundle under `modules/lib/modules/<release>/updates/<name>/`,
   compresses them with xz to match the tree, reruns `depmod -b` for that
   release, updates `bundle.json` `module_files` and sha256s the same way
   `fedora-kernel-bundle.py` does (import its helpers), regenerates
   `early-modules.txt`, and records the addition in `provenance.json`
   (`kmods` list with source blob ids and .ko sha256). Refuse to modify a bundle
   whose release differs from the module vermagic. Write into a **new** bundle
   directory (`--output`), never in place: use
   `out/liveboot/candidates/stock-rawhide-73rc3-02`.
4. Tests: `hwe/tools/test-bundle-add-kmods.py` in the existing
   `tools/liveboot/test-*.py` style with synthetic inputs (no real RPMs).

## Run for real

- Build the three modules with `hwe/tools/build-kmods-arm64.sh`; keep the
  full make output in `out/hwe/A1b/build.log`.
- Run `check-config.sh` against the bundle's `kernel.config` and
  `check-exports.sh` against the kernel-devel `Module.symvers` for each `.ko`;
  logs to `out/hwe/A1b/`.
- `modinfo` each `.ko`: vermagic must be
  `7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64 SMP preempt mod_unload aarch64`
  (or exactly what the bundle's own modules report; compare against one of them).
- Produce `out/liveboot/candidates/stock-rawhide-73rc3-02` with the three
  modules added. `early-modules.txt` there must show only
  `qcom_pmic_typec_smb2` and `qcom_fg` absent.
- Run the new test and the existing `tools/liveboot/test-*.py` suite; full logs
  under `out/hwe/A1b/`, never summarised through tail/grep.

## Report

`out/hwe/A1b/REPORT.md`: files created, exact commands, build/check/test
results with log paths, the new bundle path, the `early-modules.txt` summary,
anything skipped and why, assumptions. Stop after writing it.
