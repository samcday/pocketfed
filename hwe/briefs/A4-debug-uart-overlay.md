# Brief A4: debug UART overlay on Fedora's sargo DTB

Result of the first phone run (`out/liveboot/runs/stock-rawhide-73rc3-02-01`):
the bootloader handed off to the Fedora kernel and then nothing. Fedora's
`sdm670-google-sargo.dtb` has `chosen/stdout-path = "serial0:115200n8"` but no
`serial0` alias and no `serial@a90000` node: the SDM670 debug UART (uart12,
QUP1 SE4) is still a downstream patch. We add it with a devicetree overlay.

Fedora's blob has no `__symbols__`, so first reconstitute them from the exact
source. Read `hwe/design-notes-2026-09-15.md` §2 for the method; this brief
makes it concrete. Work only in `/var/home/sam/src/pocketfed-hwe`, write only
under `hwe/` and `out/`. No commits, no phone, no podman needed. Host tools:
`dtc`, `fdtoverlay`, `fdtget`, `fdtput` (dtc 1.8.1), `cpp`, python3 with
`libfdt` (pylibfdt) available.

Inputs:

- Fedora blob: `out/liveboot/candidates/stock-rawhide-73rc3-02/dtb/qcom/sdm670-google-sargo.dtb`.
- Exact source: `out/hwe/linux-ark-7.3rc3/` (read only), DTS at
  `arch/arm64/boot/dts/qcom/sdm670-google-sargo.dts`.
- Downstream reference for the node contents (read only):
  `/var/home/sam/src/linux-sargo-camera/arch/arm64/boot/dts/qcom/sdm670.dtsi`
  lines 1454-1467 (`uart12: serial@a90000`), the `qup_uart12_default` /
  `qup_uart12_tx` / `qup_uart12_rx` pinctrl states around line 1890 (gpio51 tx,
  gpio52 rx, function `qup12`), and `sdm670-google-common.dtsi` lines 39-41
  (`serial0 = &uart12`) and 1601-1603 (`&uart12 { status = "okay"; }`).
- Fedora's blob already has `/soc@0/geniqup@ac0000` (status okay) with an
  `i2c@a90000` child that shares the SE; leave it disabled as it is.

## Deliverables

1. `hwe/dt/tools/dtb-symbolise.py`
   - `--base <fedora.dtb> --kernel-tree <worktree> --dts <path under arch/arm64/boot/dts> --output <symbolised.dtb> --report <json>`.
   - Preprocess and compile the DTS from the tree with `cpp` + `dtc -@`
     (mirror what `scripts/Makefile.lib` does: `-nostdinc -I<tree>/include
     -I<tree>/arch/arm64/boot/dts -undef -D__DTS__ -x assembler-with-cpp`,
     then `dtc -I dts -O dtb -@ -i <dts dir>`; pass the same `-Wno-*` flags the
     kernel uses if warnings are noisy). No kernel build, no config.
   - Equivalence gate: decompile both blobs with `dtc -I dtb -O dts`, drop
     `__symbols__`, `__fixups__`, `__local_fixups__` nodes and every
     `phandle = <...>` property, normalise, and require identical text.
     Any difference is a hard failure with the unified diff in the report.
   - Injection: with pylibfdt, copy the base blob, add `/__symbols__` from
     the reference blob (label -> path), and for every symbol whose target
     node in the base lacks a `phandle`, allocate a fresh value above the
     base's maximum and add it. Never renumber existing phandles. Verify every
     symbol path exists in the base. Output the new blob plus a report with
     base sha256, reference sha256, tag/commit of the tree, symbol count,
     phandles added.
2. `hwe/dt/overlays/sdm670-google-sargo-debug-uart.dtso`, compiled with
   `dtc -@ -I dts -O dtb` (use the tree's headers for `GIC_SPI`,
   `IRQ_TYPE_LEVEL_HIGH`, `GCC_QUPV3_WRAP1_S4_CLK`, `SDM670_CX`,
   `MASTER_BLSP_2`/`SLAVE_BLSP_2`/`MASTER_AMPSS_M0` via the same cpp step):
   - fragment targeting `&qupv3_id_1` (or by path `/soc@0/geniqup@ac0000` if
     that label does not exist in the symbolised base; check the report) adding
     `serial@a90000` exactly as downstream, `status = "okay"`. If the
     `interconnects` labels (`aggre2_noc`, `config_noc`, `gladiator_noc`) are
     not present in the base, drop the two interconnect properties and note it.
   - fragment targeting `&tlmm` adding `qup_uart12_default` with `tx-pins`
     (gpio51) and `rx-pins` (gpio52), function `qup12`.
   - fragment targeting `/aliases` setting `serial0 = "/soc@0/geniqup@ac0000/serial@a90000"`
     (aliases are path strings, no phandle needed).
3. `hwe/dt/tools/compose-dtb.py`
   - `--base <fedora.dtb> --symbolised <from step 1> --overlay <dtbo>... --output <final.dtb> --sidecar <json>`.
   - Runs `fdtoverlay -i symbolised -o final overlay...`, then verifies:
     `dtc -I dtb -O dts` of final versus base differs only by the added nodes
     and properties (record the diff in the sidecar), `fdtget` shows
     `/aliases/serial0` and `/soc@0/geniqup@ac0000/serial@a90000/status = okay`,
     and `dtc -I dtb -O dtb` round-trips. Sidecar: base sha256, overlay
     sha256s and sources, output sha256, symbolise report path.
4. `hwe/tools/bundle-set-dtb.py`: like `bundle-add-kmods.py` but replaces the
   DTB in a candidate bundle, writing a **new** bundle directory with updated
   `bundle.json` sha256 and a `provenance.json` entry pointing at the sidecar.
   Reuse the helpers in `hwe/tools/fedora-kernel-bundle.py`.
5. Tests: `hwe/dt/tools/test-dtb-symbolise.py` and
   `hwe/dt/tools/test-compose-dtb.py` with tiny synthetic DTS inputs compiled
   at test time with the host `dtc` (equivalence pass, equivalence fail,
   phandle allocation, overlay application, alias set). Existing style:
   `tools/liveboot/test-*.py`.

## Run for real

- Symbolise the Fedora blob; put the report at `out/hwe/A4/symbolise.json`.
  If the equivalence gate fails, stop there and report the diff: do not
  "fix" it by editing sources.
- Compile the overlay, compose, and create
  `out/liveboot/candidates/stock-rawhide-73rc3-03` from `-02` with the
  composed DTB. `early-modules.txt` must be unchanged.
- Run the new tests and the existing `tools/liveboot/test-*.py` suite; full
  logs under `out/hwe/A4/`, never summarised through tail/grep.

## Report

`out/hwe/A4/REPORT.md`: files created, commands, equivalence result (with the
symbol and phandle counts), the exact node/property diff the overlay produced,
test results with log paths, the new bundle path, anything dropped (for
example interconnect properties) and why. Stop after writing it.
