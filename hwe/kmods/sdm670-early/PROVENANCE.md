# Provenance: sdm670-early external kmods

These sources are verbatim copies from the exact kernel-ark tag that Fedora
built `kernel-7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64` from. No driver
source was edited.

- Worktree: `out/hwe/linux-ark-7.3rc3` (read-only input)
- Tag: `kernel-7.3.0-0.rc3.704340f1cd0d.32`
- Commit: `2568f046a45a2d2fb93a82acf0cebde8a21d3565`

## Copied files

| Copied path | Upstream path | Git blob |
| --- | --- | --- |
| `src/pinctrl-sdm670.c` | `drivers/pinctrl/qcom/pinctrl-sdm670.c` | `533b87c39cd5bd5813b1fcb5d6149139cc219c0b` |
| `src/pinctrl-msm.h` | `drivers/pinctrl/qcom/pinctrl-msm.h` | `b94ba1a4177ede95042e74a39fcc93eba046063d` |
| `src/sdm670.c` | `drivers/interconnect/qcom/sdm670.c` | `9280921d44d2be6f260fccfbe4d035584e79b55b` |
| `src/icc-rpmh.h` | `drivers/interconnect/qcom/icc-rpmh.h` | `09d8791402dc4bd67fd092268eb1458bcd8c6c8f` |
| `src/bcm-voter.h` | `drivers/interconnect/qcom/bcm-voter.h` | `b4d36e349f3c0dcedc26c83b015589e6c7753609` |
| `src/panel-samsung-s6e3fa7.c` | `drivers/gpu/drm/panel/panel-samsung-s6e3fa7.c` | `f4d75eca3cdfa27441fbb1e303dd8894257d4397` |

Private headers not under `include/` are copied because the drivers include them
with quotes: `pinctrl-msm.h` for the pin controller, `icc-rpmh.h` and
`bcm-voter.h` for the interconnect provider. Everything those headers pull in is
either a standard `<linux/...>`/`<soc/qcom/...>`/`<dt-bindings/...>` header
already shipped by kernel-devel.

`src/bcm-voter.h` includes `icc-rpmh.h`; `src/icc-rpmh.h` includes the
dt-bindings `qcom,icc.h`; `src/pinctrl-msm.h` only includes core headers.

## Module map

| Module | Built from | In-tree Kconfig |
| --- | --- | --- |
| `pinctrl-sdm670.ko` | `src/pinctrl-sdm670.c` | `CONFIG_PINCTRL_SDM670` (unset) |
| `qnoc-sdm670.ko` | `src/sdm670.c` | `CONFIG_INTERCONNECT_QCOM_SDM670` (unset) |
| `panel-samsung-s6e3fa7.ko` | `src/panel-samsung-s6e3fa7.c` | `CONFIG_DRM_PANEL_SAMSUNG_S6E3FA7` (unset) |

The machine-readable form of this table is `sources.json`, consumed by
`hwe/tools/bundle-add-kmods.py` when it records the additions in a candidate
bundle's `provenance.json`.
