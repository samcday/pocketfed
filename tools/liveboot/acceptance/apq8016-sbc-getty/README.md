# DB410c ttyMSM0 root-autologin acceptance fragment

Disposable, liveboot-only userspace fragment for the DB410c full-Fedora fixture. It
makes the serial getty on `ttyMSM0` log `root` in automatically so a hardware
trial's userspace handoff is observable over the board's UART console. It is never
applied to an installed or production system and contains no state, secrets or
device-specific data.

## Files

- `usr/lib/systemd/system/serial-getty@ttyMSM0.service.d/10-autologin.conf`:
  per-instance drop-in that clears the vendor `ExecStart=` and replaces it with
  `agetty --autologin root`. `--autologin root` runs `login -f root`, which skips
  password authentication; the image's `root` shadow entry is `!unprovisioned`,
  which `-f` bypasses. `%I` is the instance `ttyMSM0`, so agetty opens
  `/dev/ttyMSM0`; `/sbin/agetty` resolves through `/sbin -> usr/sbin -> bin` to
  the same binary the vendor unit uses.

## Why no explicit enablement symlink

The unit is auto-instantiated, so no `getty.target.wants` symlink is needed:

- `serial-getty@.service` ships with `[Install] WantedBy=getty.target`.
- `getty.target` is statically wanted by `multi-user.target`, which the DB410c
  profile boots.
- `systemd-getty-generator` instantiates `serial-getty@<dev>` for each active
  serial console read from `/sys/class/tty/console/active`; the profile command
  line sets `console=ttyMSM0,115200n8`.

## Applying it

Layer it over the tracked `overlays/apq8016-sbc` overlay at fixture-export time,
the same way the graphical acceptance fragment is applied:

```sh
overlay=out/liveboot/<trial>/overlay
mkdir -p "$overlay"
cp -a tools/liveboot/overlays/apq8016-sbc/. "$overlay/"
cp -a tools/liveboot/acceptance/apq8016-sbc-getty/. "$overlay/"
rm -f "$overlay/README.md"   # documentation, not guest payload
```

This README sits in the tracked fragment next to its payload but is excluded from
the applied overlay, so it never lands in the guest root. The fixture manifest
records every remaining overlay file hash, sealing the drop-in.
