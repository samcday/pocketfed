# Fingerprint trial image, staging and rollback

Prepared from read-only device metadata at 2026-09-10 23:37–23:40 UTC. No
phone deployment, pin, module, GPIO, TA or biometric-storage change was made.
Refresh the snapshot immediately before staging: concurrent phone tasks can
change this state. Kernel binaries must come from [COPR 10973843](https://copr.fedorainfracloud.org/coprs/build/10973843).

## Current baseline to preserve

- Booted `.8`, slot **b**. Deployment
  `ae313ebc772138e011a4a0a42b0f2d4247769433f4a1208b1824a062a78f7cfa.0`.
- Image reference:
  `ghcr.io/samcday/sam-sargo@sha256:b4864c59ae9679bc7feb87907c2e49a81abc97c48f47e70f32c080d356857505`.
  There is no staged deployment and no rpm-ostree transaction in the snapshot.
- Booted deployment is **not pinned**, and `/usr` has a transient development
  overlay. Comparing its RPM database against the persistent deployment shows
  four added packages: `lpa-gtk-0.4-1.4.pocketfed.fc46.noarch`,
  `python3-cairo-1.28.0-8.fc45.aarch64`,
  `python3-gobject-3.57.1-6.fc46.aarch64` and
  `python3-gobject-base-3.57.1-6.fc46.aarch64`. Pinning an OSTree deployment does
  not capture this overlay. Include these exact reviewed RPMs in the trial
  image, and retain their artifacts for recovery before reboot.
- Requested persistent replacements are `81voltd-1.2.0-1.1.pocketfed.fc46`,
  `ModemManager` and `ModemManager-glib` at `1.24.2-5.1.pocketfed.fc46`, and
  `gtk4-4.23.4-1.1.pocketfed.fc46`. Retain all four requests, the `tailscale`
  layer, local `feedbackd-device-themes-0.8.9-1.fc46.noarch`, and the current
  absence of removals. All are aarch64 except the stated noarch package.
- Initramfs regeneration is enabled with `--hostonly --hostonly-mode=strict
  --no-hostonly-cmdline --no-hostonly-default-device`. Preserve it and the
  deployment's existing kernel options; only its OSTree target changes.
- Existing rollback is `0707638198ae6b8261db4eca20aa2f6ab650999dc7df8c10fa12daeba2680961.0`.
  Existing pinned deployments begin `b2b5f35b40e9`, `5ff2bf7e2065`, and
  `16b4d13b8c30`. Leave them pinned and keep their complete deployments.

Exact IDs, requests, options, slot links and BLS entries are in
`validation/device-baseline-20260911.json`; exact live/persistent RPM inventories
and unchanged critical boot-helper hashes are in
`validation/device-overlay-20260911.json`. `bootc` reports this layered,
transiently unlocked installation as incompatible, so use the existing
rpm-ostree deployment workflow rather than switching management tools.

## Why a kernel RPM override alone is insufficient

The image recipe owns `/usr/lib/modules/$kver/{aboot.img,initramfs.img}`. Kernel
RPMs provide the new kernel, modules and DTB, but not these image-owned files.
The inherited finalizer replaces the ABLX kernel/initramfs and command line
inside an Android-v2 template; it copies the template's outer ABL shim, second
stage, recovery payload and **DTB** unchanged. See
`devices/google-sargo/pocketfed-aboot-finalize`, `repack_boot_image()`.

The `.9` camera recipe could reuse its `.8` DTB because that kernel changed no
DTS. `.10` adds `/fingerprint`; retaining that older DTB prevents creation of
`/dev/fpc1020`. The camera trial's unchanged-DTB assertion must become a
new-DTB equality and positive-compatible assertion. Do not reuse that script
unchanged and do not replace the current device verifier with the stale
checked-in `.3` verifier.

## Offline image construction

Use the newest coordinated immutable image as the base, initially the digest
above. A previously prepared camera image adds unbooted userspace changes; use
it only if the coordinating task deliberately includes that work. The `.11`
kernel already preserves the `.9` camera source fix by ancestry.

`image/Containerfile.kernel` and `image/install-kernel.sh` are an isolated
kernel build step for the outer fingerprint image. They completed against the
verified COPR binaries, producing local image
`75f0e4d55e97863818e038e7c7b04ff32c0534702ecae66614f1abd565a0eba0`.
The earlier `.10` stage and its historical validation are retained separately.
The kernel stage has not been booted on the phone. It requires a
container, checks input hashes, installs exactly the existing kernel package
family, preserves unrelated RPM versions, generates strict `.11` initramfs,
updates only the inherited verifier's release token, replaces the DTB, and
runs the inherited finalizer. Build-only `fdtget` and libfdt are mounted from a
separate tool stage; they are not installed into the candidate RPM database.

Create a temporary build context containing:

```text
Containerfile                 # image/Containerfile.kernel
install-kernel.sh             # image/install-kernel.sh
replace-template-dtb.py       # ../replace-template-dtb.py
kernel-rpms/SHA256SUMS         # manifest of independently verified COPR RPMs
kernel-rpms/kernel*.rpm        # exact .11 artifacts, no debug/devel additions
```

Build that stage locally with the immutable base supplied explicitly, for
example `podman build --layers --pull=never --network=none --arch=aarch64
--build-arg BASE_IMAGE=<coordinated-immutable-base>
--build-arg DT_TOOLS_IMAGE=<verified-immutable-tools-stage>
-t localhost/sam-sargo:fingerprint-kernel11-20260911 <temporary-context>`.
The verified cached tools stage is
`02134341e7d977855115c68bdb9cc71c8a229b433d9ee4ed89ce33253f20895d`
(dtc/libfdt 1.8.1-6); it supplies only temporary build tools.
The outer image must also include the approved native fingerprint userspace
and four eSIM overlay packages above, while retaining all other base package
versions and authentication files. The current outer recipe selects 19 exact
runtime RPMs, including listener 1.3, broker 0.2 and the inactive SELinux module.
Its reviewed compiled policy/context outputs are inserted from the complete
offline distribution-store build. Five service/socket masks prevent automatic
fingerprint, broker and provisioning activation. Do not run `install-kernel.sh` on the phone.

`replace-template-dtb.py OLD_TEMPLATE NEW_DTB NEW_TEMPLATE` changes only the
DTB and Android payload checksum/DTB-size field. It checks Android-v2 structure,
existing checksum, the Sargo compatible and fingerprint firmware name, and the
64 MiB size bound. It refuses an existing output. The local test covers larger
DTBs, all inherited payloads and header fields, corrupt checksums, truncation,
and the real compiled `.10` Sargo DTB; it performs no flashing.

Run the final image's full inherited `pocketfed-verify-oci` and `bootc container
lint`. Adapt/reuse the independent parser in
`devices/google-sargo/camera-trial/image-facts.py`: it must prove that embedded
kernel, initramfs and DTB exactly match the single `.11` module directory and
that the boot image fits the partition. Compare the outer ABL shim and all
unrelated base files/packages against the selected base. Expect the DTB hash to
change; require its `/fingerprint` compatible and GPIO properties. Verify
`fpc1020.ko` and `qseecomtee.ko` vermagic and dependencies from the signed COPR
artifacts. Verify the new services' permissions and startup policy offline.

Publish only an explicit trial image reference after those checks, and capture
its immutable digest. Do not update the normal device tag or kernel feed.

## Controlled staging boundary

These are proposed mutation commands, **not commands executed by this audit**.
The phone's availability for staging/activation is not established. Coordinate
with the root task and user before crossing this boundary. Check physical
recovery access before a kernel that may wedge secure firmware is activated.

1. Refresh `rpm-ostree status --json`, `ostree admin status`, `rpm-ostree kargs`,
   `qbootctl -x`, current packages and `/ostree/root.{a,b}`. Confirm no competing
   transaction or pending deployment. Save the exact live overlay delta and
   artifacts separately; a rollback of OSTree cannot restore it automatically.
2. Pin the currently booted complete deployment with `ostree admin pin booted`.
   Verify its checksum and every previous pin are still present. At the audited
   baseline this protects `ae313ebc...`; resolve current identity again.
3. Stage the immutable trial using the installed command's finalization lock:

   ```sh
   rpm-ostree rebase --skip-purge --lock-finalization \
     ostree-unverified-registry:ghcr.io/samcday/sam-sargo@sha256:TRIAL_DIGEST
   ```

   Keep existing package requests and overrides. Compare the new deployment's
   requested packages/replacements/removals, initramfs arguments and boot
   options against the snapshot. If the transient overlay or package solver
   prevents staging, resolve the specific issue without clearing unrelated
   overrides, unpinning recovery deployments, or forcing a boot change.
4. Read the staged root and BLS artifacts. Verify one `.11` module directory,
   matching template/initramfs/DTB, exact trial packages and old pins. Finalize
   a **temporary output file** with the staged BLS options and independently
   inspect its embedded DTB and ABLX payload before activation. Calling the
   Python finalizer with a regular temporary output does not flash; invoking
   `aboot-deploy` does flash and is not an inspection command.
5. When the user is ready, activate the exact staged checksum:

   ```sh
   rpm-ostree finalize-deployment STAGED_CHECKSUM
   ```

   Its installed help explicitly says this **unlocks finalization and reboots**.
   Do not treat it as a harmless unlock. The OSTree Android boot hook finalizes
   and writes the inactive slot, updates that slot's root link and activates
   it through qbootctl. In this snapshot the candidate would use slot **a**,
   preserving currently booted slot **b**. Recheck the actual slot first.

After reboot, verify `.11`, the running `/fingerprint` DT node, both module
identities and misc/TEE discovery before any TA request. Then perform one
controlled common-library/app initialization with listener logging and a
recovery path. An `EBUSY`/unsupported reentrant result is a stop condition for
that attempt, not a reason to retry blindly.

## Rollback

For a booted but failing candidate, read the fresh deployment ordering and
confirm the rollback checksum is the preserved baseline. Then use
`rpm-ostree rollback` and inspect the selected deployment before a coordinated
reboot. If another task has changed ordering, resolve the exact saved checksum
in `ostree admin status` and select that current index with
`ostree admin set-default INDEX`; never assume a saved numeric index still
identifies the same deployment. Keep all earlier pinned deployments.

For loss of Linux/tailnet access, physical bootloader recovery is required.
The first trial should have left the previously booted slot and its root link
intact; confirm the saved slot mapping before selecting that slot in the
bootloader. At the audited baseline it is slot **b**. Do not overwrite either
boot partition or erase userdata to undo this trial. The recovered persistent
`.8` deployment will not contain its former transient eSIM overlay; restore
those reviewed packages through the normal persistent image/package workflow.

## Listener compatibility evidence

The exact FPC TA imports `qsee_fts_read_file`, `qsee_fts_write_file`, SPI and
wrapped inter-app-message decoding helpers. The source investigation found no
cross-TA command-send import, and stock HAL calls Keymaster and then FPC
sequentially. This establishes ordinary storage callbacks and provides no
positive evidence of FPC-to-Keymaster nested calls. It does **not** prove which
QSEE scheduler statuses this firmware returns. The kernel's ordinary INCOMPLETE
listener path is implemented; CONTINUE_BLOCKED/reentrant handling remains
unimplemented and must be assessed during the controlled first trial.
