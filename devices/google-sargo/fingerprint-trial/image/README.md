# Local fingerprint trial image

The current local candidate includes the production enrollment broker and the
reviewed SELinux integration. It built and passed independent offline comparison
on 11 September 2026. It is not published, staged or booted. No sensor,
trusted-app, provisioning, enrollment or authentication operation has run on the
phone through this trial.

- Current candidate: `localhost/sam-sargo:fingerprint-candidate-v3-20260911`
- Immutable image ID:
  `671197f9f3bf539fc4e1fd138843a8739df3958cabcacd0e5f9ca6a3baaa9996`
- Kernel stage:
  `75f0e4d55e97863818e038e7c7b04ff32c0534702ecae66614f1abd565a0eba0`
- Proven working base:
  `7abbae67bf384120c183f236b02909dc398f01ff929a565fc4b10865f0655b85`
  ([base-equivalence evidence](../base-equivalence.json)).

Kernel `.11` comes from COPR 10973843 and retains the camera `.9` changes and
fingerprint transport/DT work from `.10`. It adds complete clearing of the
kernel invoke staging allocation before release. The image embeds its matching
fingerprint DTB and strict initramfs while preserving the outer Android boot
shim and inherited boot arguments. Cached, verified dtc/libfdt tools were mounted
only during the build; the kernel and userspace builds used no network.

The outer transaction installed exactly 19 reviewed runtime RPMs. The
[artifact manifest](runtime-artifacts.json) records their versions and hashes.
It includes qsee-supplicant 1.3 (COPR 10973847), broker 0.2 (10973881), policy
module 0.1 (10973947), libfprint (10973705), fprintd, the QSEE diagnostic,
corrected Phosh 1.5, Control Center, the scoped PAM helper and the six exact live
package extras from the last successful inventory. All input signatures were
verified before selection. Unrelated base packages, including modem and GTK
versions, are unchanged.

Five units are masked before RPM installation and remain masked in the image:
`fprintd.service`, `qsee-supplicant.service`, `phosh-fingerprint-auth.socket`,
`pocketfed-fpc-auth.socket` and `pocketfed-fpc-provision@.service`. The broker and
explicit provisioning unit are installed, but no credential directory, broker
socket or fingerprint database initialization marker exists. The working Phosh
and greetd/Phrog PAM files remain unchanged.

The policy was compiled through a reconstructed complete distribution module
store. The baseline compiled policy and context text were first proved identical
to the working image. Inserting the fingerprint module then passed access,
credential-isolation and complete preservation checks outside the reviewed
additions. Only the resulting `policy.35`, `file_contexts` and ARM64-compiled
`file_contexts.bin` are replaced in this image. The runtime module-store layout
is unchanged. [Policy artifacts](policy-artifacts.json) bind the exact old/new
bytes to the signed module and prior validation evidence. No policy was loaded
or files relabeled on the phone.

The inherited `pocketfed-verify-oci` passed. `bootc container lint` reports ten
passed checks, one skipped check and the same four warning categories as the
working base: composefs configuration, runtime directories, logs and `/var`
tmpfiles. The independent comparison verifies all 19 package versions, all 107
initramfs module paths and critical configuration, the new DTB/kernel, unchanged
outer shim, PAM, exact installed units, five masks, policy outputs and mutable
paths. The only added mutable paths are the same four empty directories as the
earlier candidate; no broker credential state is initialized.

A disposable copy of this immutable ARM64 image also passed context lookup for
FPC/public TEE, privileged/out-of-range TEE negatives, broker state/socket and
executable labels. Its complete installed fingerprint unit graph passed
`systemd-analyze verify` after removing masks only inside that discarded
container. No services or hardware commands were started. Nine altered-image
fixtures are rejected by the comparator; four malformed policy-input fixtures
are rejected before destination access.

Evidence is in [v3-result.json](validation/v3-result.json),
[v3-comparison.json](validation/v3-comparison.json),
[v3-boot-facts.json](validation/v3-boot-facts.json), and
[v3-runtime-layout-checks.json](validation/v3-runtime-layout-checks.json).
Complete local build logs and facts are under
`/tmp/sargo-fingerprint-image-v3/validation`.
These results establish offline consistency, not trial boot, real labels,
secure-storage behavior, enrollment, matching or desktop authentication.

Only the source firmware extractor, hashes and static loader units are included.
No stock fingerprint/Keymaster firmware, private analysis files, templates or
credentials were added to the build context or image. Firmware preparation and
all live operations remain separate controlled steps.

## Reproduction

Run `build.sh KERNEL_IMAGE VERIFIED_RUNTIME_RPMS VERIFIED_POLICY_INPUTS
NEW_CONTEXT LOCAL_IMAGE_TAG` with the immutable kernel stage above. The runtime
directory must contain exactly the selected 19 RPMs and `SHA256SUMS`. The policy
directory must contain exactly `policy.35`, `file_contexts`, `file_contexts.bin`
and a `manifest.json` identical to `policy-artifacts.json`.

The input check rejects unlisted files, symlinks, malformed names and altered
bytes. The build context is assembled from explicit sources; the shared working
repository is never sent as a whole. `install-userspace.sh` fails on missing
dependencies, unexpected names, version drift or unrelated changes. Policy
installation validates every baseline destination before changing any file,
checks the installed signed module payload, and preserves file modes/ownership.
The manifest is an integrity record and does not replace signature verification.

Use `verify.sh LOCAL_IMAGE NEW_EVIDENCE_DIRECTORY SUCCESSFUL_BUILD_LOG
BASELINE_LINT_LOG` for the independent comparison. The current runtime and
policy manifests describe v3, not the earlier image.

The earlier valid `.10` image `83cc5287c9ae` remains available with its historical
17-package evidence under `validation/final-*.json` and
`/tmp/sargo-fingerprint-image/validation-final-r2`. It lacks the new broker and
policy. The still-earlier `d00f4e30950d` image was rejected for a Phosh PAM
regression. The previous recipes are saved locally under
`/tmp/sargo-fingerprint-image-v3/previous-image-recipe` and
`previous-kernel-recipe`.

For recovery preparation and deployment, follow the
[controlled trial procedure](../../../../packages/kernel-fingerprint/trial-procedure.md).
Refresh the phone's deployment, overlays and recovery pins before staging. The
connection recovered after the earlier SSH/tailnet timeouts. The refresh at
2026-09-11 03:05 UTC confirmed the same deployment, pins, package inventory,
boot arguments and 46 authentication/device-configuration paths. There is no
staged deployment or transaction. Keep the image local and services masked until
the user's recovery/touch window is established, and refresh again if delayed.
