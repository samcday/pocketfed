# Bounded early-Plymouth installed trial

This opt-in image iteration retains the selected image's kernel, package set,
theme and native-display handoff. Only the initrd startup policy changes:

1. After udev starts, trigger and wait for only DRM/framebuffer events, bounded
   to two seconds plus a one-second kill grace. Failure falls back to normal
   coldplug and does not fail boot health checks.
2. Start Plymouth and the ordinary broad coldplug in parallel after that step.
   Preserve the rest of Plymouth's packaged unit and all driver preload policy.

This exercises earlier startup with the installed Plymouth binary. Driver-based
recognition of DT simpledrm and deeper coldplug work remain separate research.

Build from the repository root with an immutable, already-cached base:

```sh
podman build --arch arm64 --pull=never --network=none \
  --build-arg BASE_IMAGE=sha256:YOUR_VERIFIED_IMAGE_ID \
  -f devices/google-sargo/plymouth-early-trial/Containerfile \
  -t localhost/sargo:plymouth-early-trial .
```

Pin the current successful installed deployment before staging. Preserve package
overrides and verify the staged kernel/DTB/initrd against the built artifacts.
For one measured boot, add `plymouth.debug=stream:/dev/null` to the deployment's
arguments; the buffered trace records rendering without streaming over UART.
Stage only when Sam requests a trial to reboot himself. No boot-time improvement
is established by image checks: record first scanout, native DRM/Phrog handoff,
the optional helper result, and normal qbootctl slot success after the trial.
