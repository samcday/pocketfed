# Local kernel and userspace trials

Use this path first for PocketFed camera, fingerprint, kernel-driver and related
userspace experiments. kboop assembles a fastboop RAM boot from a cached device
rootfs and a coherent kernel/DTB/modules set. The trial needs no public CI, COPR,
published OCI, OSTree deployment or installation partition images. Keep packaging
and installed-system checks as the promotion gate after the experiment works.

The reusable source lives here and in the normal sibling `../kboop` checkout.
`out/liveboot/` is generated state: fixtures, candidates, run artifacts and logs.
The earlier `out/liveboot-dev` checkouts are historical development material and
are not needed by these commands. `just fastboot` is the installation-image
builder; `just liveboot-*` is this independent development loop.

## Host setup

Use the kboop version containing `--kernel-bundle`, `--prepared`, ABLX ramdisk
support, and `--resident-root`. Build an optimized host CLI and a static ARM64
init as described in [`../kboop/README.md`](../../../kboop/README.md):

```sh
cd ../kboop
cargo build --release --locked -p kboop-cli
# See kboop README for the static ARM64 linker/toolchain invocation.
cd ../pocketfed
just liveboot-help
```

The runner defaults to `../kboop/target/release/kboop` and
`../kboop/target/aarch64-unknown-linux-musl/release/kboop-init`; `--kboop` and
`--init` override these. Each preparation snapshots both binaries into its run,
so rebuilding a tool does not invalidate a previously prepared boot.

Fixture export uses host `/usr/bin/python3`, Podman, erofs-utils, zstd, checkpolicy,
libsepol and Python setools. The ARM64 container is never started. A local source
kernel build additionally needs its cross compiler, Kbuild dependencies and kmod
(`depmod`/`modinfo`). This host's cross tools work with `PATH=/usr/bin:/bin`.

## Prepare userspace once

From the PocketFed repository root, choose an already cached image. Resolve a
local tag to its full immutable ID, or use a registry reference pinned by digest:

```sh
image="$(podman image inspect --format '{{.Id}}' localhost/my-sargo:trial)"
image="sha256:${image#sha256:}"
fixture=out/liveboot/fixtures/my-sargo-trial
just liveboot-fixture \
  --image "$image" --output "$fixture" \
  --dtb qcom/sdm670-google-sargo.dtb --reuse
```

There is no pull, image build, image push or container execution in this step.
The source must be a complete device OCI containing its baseline kernel, DTB,
modules, config, firmware and production `aboot.img` shim. A bare Fedora base is
not a Sargo device image. The supplied Sargo profile records a known `.8` baseline
image reference if a starting point is needed.

The exporter mounts a throwaway writable copy, extracts the baseline bundle and
shim, removes the packaged module tree from that copy, applies the trial overlay,
and exports EROFS. It prunes unused OSTree object hardlinks so their `default_t`
labels cannot overwrite the live executables' labels. Full decoding and actual
systemd/bash/journald/reporter labels are checked before accepting the fixture.

`just liveboot-fixture` includes the disposable service overlay and `--smoo-policy`.
This patches **this source image's own policy**, preserving every original policy
form and adding only `(allow kernel_t device_t (io_uring (cmd)))` if absent.
`smoo-policy.json` records the semantic delta and hashes. Never copy a binary
policy from another fixture: that can erase camera/fingerprint policy additions.

Use `--overlay path/to/overlay` to supply your own complete trial overlay. Copy
`tools/liveboot/overlay` as a starting point, then add locally built binaries,
configuration, public SSH keys or test services at their target paths. This avoids
an image build for small userspace changes. Network configuration and access keys
belong in private generated overlays, not tracked source. Alternatively export a
locally built device OCI that already includes the trial userspace. Both paths
preserve source image layers and write only disposable runtime state on the phone.

Each fixture contains `fixture.json`, `rootfs.erofs`, `kernel-bundle/`, production
shim files, and label/policy evidence. `--reuse` verifies exact inputs and all
artifacts. A changed image, overlay or exporter needs a fresh fixture directory;
never overwrite an accepted fixture. Kernel-only iterations reuse the same root.

## Build a local kernel candidate

Keep one configured Kbuild output directory per source/configuration lane. Seed
it with the appropriate full device configuration, review config changes with
`olddefconfig`, and reuse that build directory for subsequent edits:

```sh
tree=/path/to/linux
build=/path/to/kernel-build
candidate=out/liveboot/candidates/camera-01
PATH=/usr/bin:/bin just liveboot-kernel \
  --kernel-tree "$tree" --build-dir "$build" \
  --output "$candidate" --dtb qcom/sdm670-google-sargo.dtb --jobs 8
```

Add `--no-build` to package an already completed build. It still installs modules
into the new candidate directory and runs depmod; it never installs them on the
host or phone. GCC cross prefixes, LLVM and explicit Kbuild flags are supported;
run `tools/liveboot/build-kernel.py --help` for options.

The bundle includes Image.gz, DTB, the complete module tree and depmod metadata,
full config, System.map, source commit/dirty patch, commands and toolchain
provenance. Release, Image banner, module vermagic, module completeness and input
drift are checked. An incomplete object-only kernel check is not a boot candidate.
`bundle.json` is compatible with the strict kboop bundle contract. Prepared runs
record the candidate's actual config; they never substitute the fixture's config.

## Prepare and boot

Select the designated test device and its independently identified UART. On this
host, test-sargo is serial `99NAY1AZG1` and its FTDI adapter is
`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0`. Inspect current
ownership; do not assume an adapter or phone is free because an old run ended.

```sh
run=out/liveboot/runs/camera-01
just liveboot-prepare \
  --fixture "$fixture" --kernel-bundle "$candidate/bundle.json" \
  --device-serial 99NAY1AZG1 --run-dir "$run"

# Put the verified test phone in fastboot, then:
just liveboot-boot --run-dir "$run" \
  --uart /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0
```

Omit `--kernel-bundle` for the fixture's baseline kernel. Preparation is host-only.
The explicit fixture chooses userspace; its DTB must match the device profile,
and its exact image identity is recorded even when it differs from the profile's
baseline. The runner checks required early modules and generates a product plus
exact-serial fastboop profile. It snapshots immutable boot artifacts before USB
access. The Sargo early-module order is in `profiles/google-sargo-initrd.conf`,
independent of installed-deployment dracut policy.

The default profile starts `multi-user.target`. To test the graphical desktop or
change driver command-line options, make a reviewed profile derived from
`profiles/google-sargo.json` and pass `--profile` to preparation. Keep the run token,
SysRq and required platform supplier ordering. The full image userspace remains
available; the initial handoff checkpoint does not test camera capture, biometric
authentication, charging or the desktop.

`run.json` records image/tool/config/bundle hashes, command line and preparation
time. `prepare.log`, `host.log`, `uart.log`, `prepared.json` and `result.json`
retain evidence. The reporter must match this exact run, release and root mode.
It checks enforcing SELinux, disposable overlay root, matching modules, successful
writable-root relabeling and transport readiness; other failed services are
reported as diagnostics. Each subsystem still needs its own acceptance scenario.

## USB root or RAM root

Use the default `--root-mode usb` for quick camera/fingerprint and most driver
iterations. kboop streams EROFS on demand. Keep hosting and the data connection
alive until the disposable session ends. Pass, failure and timeout do not stop
USB-root hosting. Stopping it while the phone uses that root breaks the session.

For controller resets, role switches, cable removal or other tests that interrupt
USB, prepare with `--root-mode ram`:

```sh
just liveboot-prepare \
  --fixture "$fixture" --kernel-bundle "$candidate/bundle.json" \
  --root-mode ram --device-serial 99NAY1AZG1 \
  --run-dir out/liveboot/runs/typec-01
```

Resident init checks available memory, copies both compressed EROFS images into
`noswap` tmpfs, verifies exact lengths and SHA256, mounts readonly loop devices,
and then unbinds/removes the bootstrap USB gadget and stops device smoo. It fails
rather than falling back to a transport-dependent root. The copies need their
combined size plus a 768 MiB reserve and a small metadata margin. The full `.11`
fixture uses roughly 1.75 GB of compressed root/modules, so this mode has a longer
initial transfer and less spare RAM than streaming.

`/run/kboop/root-mode.json` and the UART report prove verified copies and detach.
After the matching RAM handoff passes, the runner stops the host's USB server and
continues as a UART console/control owner (`phase: console`). Thus SysRq remains
available after USB storage is gone. Wait for this proof before disrupting USB.

The default overlay still masks competing USB/Type-C userspace. For a Type-C
userspace test, derive an overlay that restores only the relevant original
services, while retaining installation/update guards. For example, removing a
`/dev/null` mask from the derived overlay lets the original image's unit through;
also update that overlay's policy inventory. RAM mode permits active USB policy,
but is not evidence that the production policy or a dock was tested.

## UART recovery

Every trial includes `sysrq_always_enabled=1`. The runner owns the UART exclusively
at 115200 8N1 and exposes a private control FIFO. It arms only after observing the
exact run token in new UART output, and disarms on reboot or a different kernel.

```sh
just liveboot-sysrq --run-dir "$run" --key help
just liveboot-sysrq --run-dir "$run" --key reboot
```

The FTDI harness requires a 300-baud NUL to approximate BREAK, then restoration
to 115200 and `h`/`b`; ordinary tcsendbreak was ineffective. Commands and outcomes
are logged; inspect the device acknowledgment, not merely a successful queue.
Reboots are explicit and never triggered by timeout. SysRq returns control to
the bootloader's normal path; it cannot repair an invalid installed boot image.

One liveboot owner at a time: initial fastboot selection is serial-bound, but the
pinned native smoo runtime discovery is not serial-filtered. The runner holds
both global hosting and device/UART locks. An installed peer can still join mesh
experiments. No flash, erase, format or slot-selection command is part of this
workflow.

## Current evidence and remaining device work

The Sargo `.8` baseline passed enforcing userspace handoff and UART HELP/reboot
on 9 September. The normal-checkout USB-root run passed again on 11 September.
The local kernel producer has passed real incremental and existing-output smoke
runs; those minimal configs test the producer, not a phone boot. Current RAM-root
hardware acceptance is being recorded under `out/liveboot/runs/`.

Fajita and Crosshatch need their own serial/UART, DTB, early modules, production
shim, address recipe and source fixture. Do not copy Sargo's boot offsets or shim.
Retain Crosshatch's current GLINK quarantine until that is the explicit experiment.

Host checks:

```sh
for test in tools/liveboot/test-*.py; do
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$test" || exit
done
```
