# Powered USB-C dock validation

The normal Sargo image carries the SMB2 Type-C/PD driver from kernel release
`7.1.2-0.pocketfed.sdm670.7` and the ordinary `sdm670-google-sargo.dtb`.
The board stays dual role with a preference for taking power. Its initial PD
policy is PD 2.0, one fixed 5 V sink PDO up to 3 A, and one fixed 5 V source PDO
at 500 mA. The port remains USB 2.0 high speed (480 Mb/s). The initramfs
preloads the USB PHY, DWC3 role provider, charger, and SMB2 Type-C driver so
charger input can be enabled before the real root filesystem is mounted.

This is the next hardware validation increment tracked by
[sam-sargo#17](https://github.com/samcday/sam-sargo/issues/17). A successful image
build verifies the shipped kernel module and DTB policy; it does not prove
charging, USB enumeration, replug recovery, or rollback on hardware.

## Request host while the dock supplies power

Connect the powered Anker A8396 upstream port to Sargo. Then explicitly run:

```sh
sudo systemctl start pocketfed-sargo-typec-host.service
journalctl -u pocketfed-sargo-typec-host.service -b --no-pager
lsusb -t
lsusb
fastboot devices
```

The helper waits for a fixed 5 V PD sink/device contract, asks TCPM for exactly
one data-role swap to host, and checks that Sargo remains a PD sink with the
charger online. It does not request a power-role swap or force the USB role
controller. A failed contract check, detach, changed partner, rejected swap, or
failed sink/host postcondition returns failure. Current fields are negotiated
or programmed limits, not proof of actual 3 A draw.

Only start this service when intentionally testing the attached powered dock.
It does not start at boot or on cable attachment. Normal charging and PC gadget
attachments keep their ordinary role selection. No persistent `/etc` setting
is required; run the command again for each dock attachment being tested.

PD 2.0 identity discovery requires the data-host role in TCPM, so the helper
cannot identify the Anker before its first swap from device. After success it
reports the partner identity if available: the observed A8396 is VID `291a`,
PID `8396` (ID Header `0x6c00291a`, Product VDO `0x83960000`). Discovery may still
be pending when the helper finishes. Unknown or absent identity is reported as
such; it is not treated as proof that this is the Anker dock.

## Record the test

Record the image digest, kernel release, dock/cable/port arrangement, and each
physical action in #17. Capture the state before and after the explicit swap:

```sh
uname -r
rpm-ostree status
cat /sys/class/typec/port0/{power_role,data_role,power_operation_mode}
cat /sys/class/typec/port0-partner/identity/{id_header,product}
cat /sys/class/power_supply/tcpm-source-psy-*/{online,voltage_now,current_max}
cat /sys/class/power_supply/pm660-charger/{online,status,voltage_now,current_now,current_max}
lsusb -t
journalctl -k -b --no-pager
```

Check USB2 hubs/audio and the attached A5 fastboot peripheral first. Dock
Ethernet enumeration is a separate observation; the dock's LED color does not
establish USB link speed. Exercise both cable orientations, warm replugs,
dock power cycles, reboot with the dock attached, and ordinary charger/PC
attachments. Stop after an observed failure long enough to capture its state.
The TCPM debugfs log is consuming: coordinate its reader and save each read.

The kernel, DTB, helper, and policy travel together in the normal immutable
image. Sam validates the new deployment and retains the known-good pinned
pretrial deployment and current keyboard layers. If this increment interferes
with daily use, Sam can select the prior deployment with `rpm-ostree rollback`
and reboot; no mutable Type-C setting from this helper needs undoing.
