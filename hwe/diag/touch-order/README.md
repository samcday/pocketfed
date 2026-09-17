# Touch probe-order diagnostic (sargo, stock Fedora kernel)

Files for the liveboot overlay used in `hwe/evidence/2026-09-17-touch-probe-order.md`.
Install them into a copy of `tools/liveboot/overlay` as
`usr/libexec/hwe-touch/*` and `usr/lib/systemd/system/hwe-touch-order.service`,
add the unit to the overlay's `policy.json` `provided_units`, export a fixture
with `--overlay`, and pull the service in with
`systemd.wants=hwe-touch-order.service` plus `hwe.touch=late` or
`hwe.touch=monitor` on the kernel command line. `hwe.touch=late` expects
`modprobe.blacklist=rmi_i2c` and an initrd list without `rmi_i2c`/`rmi_core`
(`google-sargo-stock-nomsm-notouch-initrd.conf`). `hwe.nogpiodbg` skips the
PMIC GPIO and `/sys/kernel/debug/gpio` reads, which soft-lock the PocketFed
`.11` kernel.

| Tool | Purpose |
| --- | --- |
| `hwe-touch-order` | the oneshot report: GPIO levels, device links, regulator summary, optional late `modprobe rmi_i2c`, tap windows, hardware reset pulse plus rebind, low-rate monitor |
| `gpio-state` | read GPIO lines through the v2 character device without reconfiguring them |
| `attn-sample` | sample one line (the ATTN pin) at a fixed rate and count low samples/transitions |
| `gpio-pulse` | drive one line low for N ms then high (touch reset) |
| `rmi-status` | dump the RMI4 page-0 PDT and F01 status/control over i2c-dev; `--write-test` writes ctrl0 and reads it back |
| `f12-poll` | poll F12 finger data over i2c-dev without touching the interrupt status |

All output goes to the debug UART and `/run/hwe-touch-order.txt`. The tools
need only python3 and coreutils, which the PocketFed image has.
