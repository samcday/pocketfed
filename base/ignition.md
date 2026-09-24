# Ignition

PocketFed can be provisioned with [Ignition](https://coreos.github.io/ignition/)
the way Fedora CoreOS is, so a pile of phones and boards can be brought up as
identically configured nodes. Every PocketFed image ships Fedora's `ignition`
package; nothing runs unless a boot asks for it.

## Model

`fastboot boot` plays the part PXE plays for FCOS. A host RAM-boots the
device's kernel with an Ignition-capable initrd, an Ignition config appended
to that initrd, and these kernel arguments:

```text
ignition.firstboot ignition.platform.id=metal
```

Ignition's generator only looks at the kernel command line, so the same
initrd works whether the root is served over USB by liveboot or is an
installed `pfroot` deployment on the device. Flashed boot images and
userdata never carry a config or a first-boot marker: a boot is an Ignition
boot only because the host said so. If provisioning is interrupted, reflash
and boot the provisioning image again; Ignition is not idempotent over a
half-provisioned root.

| Fedora CoreOS | PocketFed |
|---|---|
| PXE: `ignition.firstboot` plus a config cpio appended by `coreos-installer pxe customize` | `fastboot boot`: the same arguments plus an appended cpio carrying `etc/ignition/user.ign` |
| Installed: `/boot/ignition.firstboot` stamp read by GRUB | Not used; Android bootloaders cannot read it |

## The initrd

Normal PocketFed initrds do not contain Ignition. Build a provisioning initrd
from the device image with the opt-in `pocketfed-ignition` dracut module,
using the device's usual dracut arguments plus:

```sh
dracut --add pocketfed-ignition ... provision-initramfs.img "$kver"
```

Never name the module in `/etc/dracut.conf.d`, and never install the result as
`/usr/lib/modules/$kver/initramfs.img`: rpm-ostree regenerations on the device
would then carry Ignition into every normal boot.

The module reuses the Ignition binary, generator and stage units from
Fedora's `30ignition` module without depending on it. `30ignition` pulls in
qemu, url-lib and the NetworkManager stack; PocketFed device configs omit
qemu and the Android boot image budget has no room for the rest. Around
Ignition's stages it adds:

- `pocketfed-ignition-guard.service` fails the boot, before any stage acts on
  the config, if the merged config needs the network or contains
  `kernelArguments`, `storage.disks`, `storage.filesystems`, `storage.luks` or
  `storage.raid`.
- `pocketfed-ignition-mount-var.service` bind-mounts the booted deployment's
  stateroot `/var` on `/sysroot/var`, so users, home directories, SSH keys and
  `/var` files land where the real root will see them. It finds the
  deployment by inode, which works for `ostree=true` with a slot suffix, an
  explicit `ostree=` path and liveboot alike.
- `pocketfed-ignition-populate-var.service` creates and labels the `/var`
  layout a fresh stateroot may lack.
- `pocketfed-ignition-finish.service` makes the cached config in `/run`
  root-only and syncs.

Failures isolate to the emergency target. Liveboot command lines often use
`rd.emergency=reboot`; use `rd.emergency=halt` while debugging a config.

## Configs

Write configs in Butane with `variant: fiot` and `version: 1.0.0`, and render
them with `butane --strict`. `fiot` rejects the storage and kernel-argument
sections PocketFed cannot honour, and emits Ignition 3.4.0, which merges with
FCOS `fcos` 1.5.0 fragments. Butane does not inspect merged children, so the
guard checks the merged result again at boot.

Supported: users and groups, SSH keys, files, directories and links under
`/etc` and `/var`, systemd units and drop-ins, and NetworkManager keyfiles.
Unit enablement works because PocketFed images boot their first boot with an
`uninitialized` machine ID, so systemd applies Ignition's presets.

Configs must be complete offline: inline `data:` sources and local merges
only. Fetch large or architecture-specific payloads, such as k3s or sysexts,
from units that run after the network is up. There is no initrd networking
yet; remote configs and Wi-Fi in the initrd are later work.

Like FCOS, every Ignition boot also merges a base config that creates a
passwordless `core` user in `adm`, `sudo`, `systemd-journal` and `wheel`.
Images carry FCOS's `sudo` group (GID 16) and its `%sudo NOPASSWD` rule, so
FCOS-style configs work unchanged. A regular `core` user also suppresses the
Phosh first-boot assistant. To provision without it, ship
`etc/ignition/base.d/00-core.ign` containing only
`{"ignition":{"version":"3.4.0"}}` in the appended cpio; a base config in
`/etc/ignition` replaces the one with the same name in `/usr/lib/ignition`.
Admin users added to Phosh images should otherwise set `system: true` so the
owner setup still runs.

## Appending a config

Until the liveboot tooling does this itself:

```sh
mkdir -p cfg/etc/ignition
chmod 0700 cfg/etc/ignition
install -m 0600 config.ign cfg/etc/ignition/user.ign
(cd cfg && find etc/ignition | cpio --quiet -o -H newc -R 0:0) >config.cpio

cp provision-initramfs.img provision.img
truncate -s %4 provision.img
cat config.cpio >>provision.img
```

The archive needs its `etc/ignition` directory entry; the kernel skips files
whose parent directory is missing. It must not contain `etc` itself, or the
initrd's `/etc` takes the archive's mode. The second archive must start on a
4-byte boundary. Keep the command line within 511 bytes: U-Boot and Pocketboot
can drop anything beyond the first Android boot image header field.

## Secrets

Configs carry password hashes, keys and tokens, and so do the provisioning
images, liveboot bundles and caches built from them. Keep them mode 0600 and
out of this repository, CI artifacts and evidence logs. Ignition prints the
whole config to the journal when it fails.
