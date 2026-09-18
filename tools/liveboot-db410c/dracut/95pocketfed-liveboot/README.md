# 95pocketfed-liveboot

A **liveboot-only** dracut module. Do not install it into a normal PocketFed
image.

The served Phosh root locks root's password, and kernel logins via `login`
prompt, so a getty alone is no way back in when liveboot goes wrong. This module
installs a pre-pivot hook (`pocketfed-liveboot-autologin.sh`) that writes a
`serial-getty@ttyMSM0` drop-in onto the copy-on-write root, enabling
`agetty --autologin root` before `switch-root`. `systemd-getty-generator`
already instantiates the unit from `console=ttyMSM0`; the hook only replaces its
`ExecStart`, and the write lands in the RAM COW layer so it disappears on the
next boot.

The hook is a no-op unless `rd.smoo` is present on the kernel command line, so it
cannot arm a normal installed system even if the module were copied in. It is
baked into the initrd by `tools/liveboot-db410c/build-initrd.sh` (which also
stages `90smoo` from the smoo checkout); see `../README.md`.
