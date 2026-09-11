# Early Plymouth on Sargo

Track initial integration in
[sam-sargo #33](https://github.com/samcday/sam-sargo/issues/33), and the separate
preserved-display-state goal in
[#32](https://github.com/samcday/sam-sargo/issues/32).

The installed image selects `quiet rhgb` and `fedora-mobile`. `quiet` reduces
console output; Plymouth also needs `rhgb` (or `splash`) to choose its graphical
renderer. The kernel can still advertise its UART as an active console without
an explicit `console=` argument. `plymouth.ignore-serial-consoles` keeps that
console from forcing Plymouth into detailed text mode; kernel UART output and
the separate verbose liveboot command line retain their existing behavior.
`UseSimpledrm=1` matters twice: it lets Plymouth use the inherited
framebuffer immediately, and makes dracut's `45plymouth` depend on `simpledrm`
instead of broad `drm` discovery. Fedora's `UseSimpledrmNoLuks=1` alone does not
select that narrow dracut dependency. `DeviceTimeout=8` is a fallback timeout,
not an unconditional delay; `ShowDelay=0` requests immediate display.

The strict initrd retains the proven storage, charging and USB supplier ordering.
MSM, display clocks and panel modules are deferred to the real root. The small
`gpucc_sdm845` clock/power-domain supplier remains preloaded: the built-in GPU
SMMU needs its `GPU_CX_GDSC` power domain before the deferred-probe deadline.
Deferring that supplier until real-root coldplug can make the SMMU fail permanently
with `-ETIMEDOUT`, followed by MSM failing to bind the GPU. This supplier does not
pull MSM or Adreno firmware into the initrd. The artifact check requires both its
module and preload entry. The panel
omission also prevents `45simpledrm` from adding every modular panel driver.
Simpledrm is built into the Sargo kernel. This does not implement preserved MSM
modesetting state or establish that the inherited ABL scanout stays valid.

`pocketfed-verify-plymouth-initrd` checks the generated artifact for Plymouth's
startup unit, renderer, plugin, font, theme animation and shared keymap target.
It rejects the broad DRM dracut module and native display/Adreno payloads. The
normal device Containerfile runs it before assembling the Android boot image,
and the final image verifier runs it again.

The theme source and reproducible SRPM generator live in
`packages/plymouth-theme-fedora-mobile`. Version 0.1.0-1.fc46 is built in the main
PocketFed COPR (10974883). Installing the RPM only makes the theme available;
the device image owns theme selection and initrd generation.

## Installed iteration with a retained custom kernel

The September 2026 user explicitly selected main COPR/image iterations on the
daily driver while the test device was unavailable. Its current fingerprint
kernel is not in the canonical kernel feed. `Containerfile.plymouth` applies
the same boot policy and signed main-COPR theme to a caller-selected immutable
image without changing the existing package set, kernel, DTB or outer ABL shim.
It fails if theme dependencies are absent; it does not resolve unrelated package
updates. This is an image build, not device access or an automatic deployment.

From the repository root, with `BASE_IMAGE` set to the verified immutable image
ID and `THEME_RPM_DIR` containing the downloaded main-COPR binary RPM:

```sh
podman build --arch arm64 --pull=never --network=none \
  --security-opt label=disable \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  --build-context theme-rpm="$THEME_RPM_DIR" \
  -f devices/google-sargo/Containerfile.plymouth \
  -t localhost/sargo-plymouth:iteration .
```

The label option permits the disposable build to read the host input directory;
it does not change host or phone SELinux enforcement. Verify the resulting
image, pin the current deployment, preserve existing overrides and Android slot
recovery, then use the normal OSTree image deployment path. Check the regenerated
deployment initrd as well as the image's initrd before rebooting.

When migrating from the old native-display preload policy, local initramfs
regeneration can retain the running deployment's old preload list even though
the staged `/etc/dracut.conf.d/60-google-sargo.conf` contains the new policy.
For an installed trial whose root-boot requirements are fully covered by this
device image, `rpm-ostree initramfs --disable` selects the verified image-supplied
initrd. Confirm the selected image, preserved package overrides, staged initrd
hash and boot arguments afterward. Do not substitute the generic image initrd
for additional host-specific boot requirements that it does not contain.

Acceptance requires an observed early splash, working prompts, continued storage
and charging, native DRM handoff and a usable greeter/session. Record both first
boot and subsequent boot: deployment-only initialization can distort timing.
Keep installed quiet defaults separate from the verbose UART liveboot defaults.
