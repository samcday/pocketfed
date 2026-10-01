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

It also installs a pre-udev hook (`pocketfed-liveboot-zram.sh`) that loads
`zram` with its lz4 back ends from the initrd. The served root cannot modprobe
this kernel's modules, and zram-generator only modprobes when
`/sys/class/zram-control` is missing, so this is what gives the 1 GB board swap.
When the builder staged `edid/1280x720.bin` next to the module, it is installed
as `/usr/lib/firmware/edid/1280x720.bin` for the kernel's `drm.edid_firmware`
override, and a pre-pivot hook (`pocketfed-liveboot-edid-fw.sh`) copies it to
`/run/pocketfed-fw` so `firmware_class.path=/run/pocketfed-fw` keeps it
loadable after switch-root, where the served root has no such file.

`rd.pocketfed.zram=0` skips it, and `rd.pocketfed.autologin=0` skips the autologin
hook; `build-initrd.sh` emits these for `--no-zram` and `--no-autologin-root`, so
the module can be present for one feature without arming the other.

All hooks are no-ops unless `rd.smoo` is present on the kernel command line, so
they cannot arm a normal installed system even if the module were copied in. The module is
baked into the initrd by `tools/liveboot-db410c/build-initrd.sh` (which also
stages `90smoo` from the smoo checkout); see `../README.md`.
