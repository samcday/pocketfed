# Brief A6: touch diagnostic overlay and fixture for the stock-kernel liveboot

State: run `out/liveboot/runs/stock-rawhide-73rc3-05-03` reached the greeter on
the stock Fedora kernel, but touch does not work. The kernel log shows
`rmi4_i2c 0-0020` probing and registering `Synaptics S3706B` as `input0` at
20.2 s, and the touchscreen DT node is identical to the working downstream
one (`interrupts-extended = <&tlmm 125 IRQ_TYPE_EDGE_FALLING>`). There is no
shell on the phone (no network on this kernel; the UART is owned by the
runner), so diagnostics must run from a service and print to the console.

Work only in `/var/home/sam/src/pocketfed-hwe`, write only under `hwe/` and
`out/`. Podman is allowed only through `just liveboot-fixture`. No commits,
no phone access. Read `tools/liveboot/README.md` ("Prepare userspace once",
overlay paragraphs) and `tools/liveboot/overlay/` first, including
`usr/lib/pocketfed-liveboot/policy.json` and how `pocketfed-liveboot-check`
consumes it.

## Deliverables

1. `out/hwe/liveboot/overlay-diag/`: a complete copy of `tools/liveboot/overlay`
   plus:
   - `usr/libexec/hwe-touch-diag` (POSIX sh, executable): waits 30 s, then
     writes a clearly delimited report to `/dev/ttyMSM0` (open it once and
     redirect the whole block; also write the same text to
     `/run/hwe-touch-diag.txt`). Sections, each prefixed `## `:
     `getenforce`; `grep -E 'rmi|tlmm|pdc|125|a84000' /proc/interrupts`;
     `ls -lZ /dev/input`; `udevadm info /dev/input/event0 | grep -E 'ID_INPUT|TAGS|SEAT|DEVNAME'`;
     `libinput list-devices` if present (else say absent);
     `loginctl seat-status seat0 | head -40`;
     `cat /sys/class/input/input0/name /sys/class/input/input0/phys`;
     `cat /proc/irq/*/actions 2>/dev/null` filtered for rmi (or
     `grep -l rmi /proc/irq/*/actions`); then print `## TOUCH THE PANEL NOW (15 s)`,
     run `timeout 15 dd if=/dev/input/event0 bs=24 count=8 2>/dev/null | wc -c`,
     then repeat the `/proc/interrupts` grep so the IRQ count delta is visible;
     `dmesg | grep -iE 'rmi|synaptics|tlmm|pdc|avc|denied' | tail -30`;
     `journalctl -b --no-pager -p warning | grep -iE 'input|libinput|phoc|seat|udev' | tail -30`;
     end with `## hwe-touch-diag done`.
   - `usr/lib/systemd/system/hwe-touch-diag.service`: `Type=oneshot`,
     `After=multi-user.target`, `ExecStart=/usr/libexec/hwe-touch-diag`,
     `StandardOutput=journal`, no `[Install]` (it is pulled in by the kernel
     command line `systemd.wants=`).
   - Update the overlay's policy inventory (`policy.json`) the way the
     existing entries do, so `pocketfed-liveboot-check` still passes; keep the
     existing masks and the check/labels services unchanged.
2. Export a new fixture from the same image as before:
   `just liveboot-fixture --image sha256:59ef70b3f9d57c56e2a86fcbbd8f948ae8655fbed6eb451b45add82b4a1b21b3 --output out/liveboot/fixtures/sargo-premouth-20260913-diag --dtb qcom/sdm670-google-sargo.dtb --overlay out/hwe/liveboot/overlay-diag --reuse`
   with full output in `out/hwe/A6/fixture-export.log`.
3. `out/hwe/liveboot/google-sargo-stock-nomsm-graphical-diag.json`: copy of
   `out/hwe/liveboot/google-sargo-stock-nomsm-graphical.json` with
   `id`/`display_name` adjusted and `systemd.wants=hwe-touch-diag.service`
   appended to `cmdline`.
4. Prepare (host-only) `out/liveboot/runs/stock-rawhide-73rc3-05-04` with that
   profile, the new fixture, kernel bundle
   `out/liveboot/candidates/stock-rawhide-73rc3-05/bundle.json`, device serial
   `99NAY1AZG1`; log to `out/hwe/A6/prepare-05-04.log`. Do not boot.

## Report

`out/hwe/A6/REPORT.md`: files created, exact commands, fixture export result
and `fixture.json` identity, prepare result, anything you could not do.
Stop after writing it.
