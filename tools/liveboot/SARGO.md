# Sargo: supplied initrd and ABLX shim

The September 22, 2026 trial RAM-booted a Pixel 3a through this consumer's
existing fastboop path. No Rust changes were needed. Use
`profiles/google-sargo-ablx-v2.yaml`: it matches `product=sargo` and the Android
v2 layout used by the retained PocketFed image recipe, with a gzip shim,
ramdisk address `0x04000000`, and separate DTB at `0x03000000`. This trial does
not validate the pinned fastboop built-in profile's Android v0/appended-DTB
layout.

## Reproduce with prepared inputs

Build with `cargo build --release --locked`. Supply a matching root, kernel,
DTB, smoo-aware dracut initrd and raw device ABLX shim. The trial reused the
existing 8 GiB Phosh root, kernel `7.1.2-0.pocketfed.sdm670.8.fc46.aarch64`,
its packaged Sargo DTB, and the production shim. The 32,224,628-byte prepared
initrd was recovered from the earlier v2 trial image as a local fixture;
independent decoding confirmed that image's kernel, shim and DTB matched the
separate inputs. This is retained-input validation, not a fresh image build
or an implementation of input extraction in this consumer.

Create `cmdline.txt` with the actual deployment's `ostree=...` path and:

```text
rw rootwait rootfstype=ext4
init_on_alloc=0 module_blacklist=rpmsg_wwan_ctrl
rd.smoo.cow.size=2G
console=ttyMSM0,115200n8 earlycon sysrq_always_enabled=1
rd.timeout=120 rd.emergency=reboot enforcing=0
pocketfed.liveboot=<unique-trial-marker>
```

The permissive SELinux setting is an existing image-recipe workaround, not
validation of enforcing mode. Omit `<S>`/`<E>` and previous root/export/COW-enable
arguments: fastboop supplies them. The prepared initrd uses ordinary smoo
interface descriptors, matching the consumer's default.

From `tools/liveboot`, with the device in fastboot:

```sh
target/release/pocketfed-liveboot bundle \
  --root-image "$SARGO_ROOT_IMAGE" \
  --kernel "$SARGO_KERNEL_BUNDLE/Image.gz" \
  --initrd "$SARGO_INITRD" \
  --dtb "$SARGO_KERNEL_BUNDLE/dtb/qcom/sdm670-google-sargo.dtb" \
  --shim "$SARGO_RAW_SHIM" \
  --device-profile profiles/google-sargo-ablx-v2.yaml \
  --serial "$TARGET_SERIAL" --cmdline-file cmdline.txt --out trial

target/release/pocketfed-liveboot image trial --output trial.img
target/release/pocketfed-liveboot boot trial --wait 30
```

Use the same cache configuration for image preparation and boot. Capture UART
at 115200 8N1. Leave the host process serving until the guest shuts down.
Fastboot selection checks the requested serial; runtime smoo selection at this
pin is still interface-based (fastboop #141). Only one eligible smoo gadget and
one competing root server should be available during this trial.

## Hardware result, September 22, 2026

Consumer runtime matching `c3f204bc`, fastboop Git `1e6d64b3`, smoo host crates
`0.0.2-rc.7`:

- Independent host decoding verified the complete 64,737,280-byte image:
  production shim, LZ4-decoded Linux kernel, unchanged initrd, separate DTB,
  expected addresses and fastboop-generated root arguments.
- Fastboop selected the requested fastboot serial, downloaded the image,
  RAM-booted it and served the root itself. No standalone smoo-host or
  PocketFed-side shim assembler was involved.
- The shim handed off to the expected kernel on Google Pixel 3a. Dracut
  connected to the export, created a disposable dm-snapshot over `/dev/ublkb0`
  with a 2 GiB RAM overlay, and switched root into Fedora 46.
- Fedora reached serial login, and the user confirmed the greeter was visible.
  The complete 8 GiB source image's SHA-256 remained unchanged after boot.

This establishes the ABLX boot and USB-root handoff on hardware. The retained
image reported a missing `qcom/sdm670/sargo/a615_zap.mbn` and GPU initialization
failure despite reaching the greeter. Desktop/GPU stability, enforcing SELinux,
reconnect behavior and
fresh input production remain separate checks. The original trial's locked
serial login also limits in-guest inspection until a lab login or temporary
debug console is available.
