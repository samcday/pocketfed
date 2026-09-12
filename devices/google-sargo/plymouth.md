# Early Plymouth on Sargo

Track initial integration in
[sam-sargo #33](https://github.com/samcday/sam-sargo/issues/33), and the separate
preserved-display-state goal in
[#32](https://github.com/samcday/sam-sargo/issues/32).

The installed image selects `quiet rhgb` and Fedora's stock `bgrt` theme.
`quiet` reduces console output; Plymouth also needs `rhgb` (or `splash`) to choose
its graphical renderer. The kernel can still advertise its UART as an active console without
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
startup unit, renderer, plugin, font, stock BGRT configuration, spinner animation,
Fedora watermark and prompt assets. It also rejects the retired custom theme.
It rejects the broad DRM dracut module and native display/Adreno payloads. The
normal device Containerfile runs it before assembling the Android boot image,
and the final image verifier runs it again.

Fedora's `plymouth-theme-spinner` package supplies BGRT and its shared spinner
assets; `fedora-logos` supplies the official watermark. The base image already
installs Fedora's system theme. No PocketFed theme package or artwork is used.
The device retains `DeviceScale=2`, `ShowDelay=0` and `UseSimpledrm=1`.

On Sargo, BGRT has no ACPI firmware image to load: the stock spinner and Fedora
watermark appear on black. Selecting this theme does not preserve the Google
splash or implement a firmware-background shim.

## Installed iteration with a retained custom kernel

The September 2026 user explicitly selected main COPR/image iterations on the
daily driver while the test device was unavailable. Its current fingerprint
kernel is not in the canonical kernel feed. `Containerfile.plymouth` applies
the stock theme and early-display policy to a caller-selected immutable image.
It removes the retired `plymouth-theme-fedora-mobile` RPM if present and verifies
that every other package, the kernel and DTB remain unchanged. It fails if the
stock theme packages are absent; it does not download or upgrade packages.
Existing additional early-start dracut modules in the base image are retained.
This is an image build, not device access or an automatic deployment.

From the repository root, with `BASE_IMAGE` set to the verified immutable image
ID:

```sh
podman build --arch arm64 --pull=never --network=none \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  -f devices/google-sargo/Containerfile.plymouth \
  -t localhost/sargo-plymouth:iteration .
```

Verify the resulting image, pin the current deployment, preserve existing
overrides and Android slot recovery, then use the normal OSTree image deployment
path. Check the regenerated deployment initrd as well as the image's initrd
before rebooting.

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

After each installed boot, verify `qbootctl.service` completed and the current
slot is marked successful before repeating reboot trials. Reaching the greeter
alone does not satisfy the boot health check. A failed service can block
`boot-complete.target` and prevent slot blessing; repeated usable boots can then
exhaust both slots' retry counters. The network-search helper treats an explicit
NetworkManager WWAN-disabled preference as a successful skip. An unknown radio
preference still follows the normal readiness checks.
