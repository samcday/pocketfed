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
| `attn-sample` | sample one line at a fixed rate. **Do not use it on ATTN**: run 08-06 window 3 carried 37 interrupts and 4080 event bytes while this sampler reported `low=0 transitions=0 first_low=never`. RMI4 ATTN is held low only until the driver reads F01 data, which is far shorter than a 10 ms poll interval. |
| `gpio-pulse` | drive one line low for N ms then high (touch reset) |
| `rmi-status` | dump the RMI4 page-0 PDT and F01 status/control over i2c-dev. `--controls` adds the F12 and F01 control blocks. `--reset-cmd` issues ten F01 software resets and reports the per-function interrupt delta, a human-free test of the whole ATTN path. `--write-test` writes ctrl0 and reads it back. The last two mutate the IC and read the F01 interrupt status, which clears ATTN behind the driver's back, so run them **after** any measurement window, never before. |
| `f12-poll` | poll F12 finger data over i2c-dev without touching the interrupt status |

Window lines report the per-function interrupt delta (`rmi4-00.fn01/fn12/fn34` separately, never the aggregate), bytes from the touch event node, and bytes from the gpio-keys node. Press a volume key in every window: a window with key bytes and no touch bytes is a true negative, a window with neither means nobody was there.

All output goes to the debug UART and `/run/hwe-touch-order.txt`. The tools
need only python3 and coreutils, which the PocketFed image has.
