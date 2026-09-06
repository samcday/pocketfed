# feedbackd device themes

PocketFed packages the unmodified upstream 0.8.9 device themes because they
were absent from the enabled Fedora Rawhide repositories on 2026-09-06.
[COPR build 10954637](https://copr.fedorainfracloud.org/coprs/build/10954637)
provides the package for the Rawhide aarch64 and x86_64 image builds.

The Phosh image explicitly installs this package. Its COPR allowlist, and the
device-layer copies of that allowlist, include `feedbackd-device-themes`.
CI checks package presence and validates the Sargo and Fajita themes.

feedbackd automatically selects a device theme using the device-tree
compatible string while the configured theme remains `default`. On Sargo,
upstream changes `button-pressed` and `key-pressed` from the generic 7 ms at
20% to 15 ms at 50%. Call and message vibration patterns are inherited.
This does not raise the driver's voltage limits or change user profiles.

The release tag `v0.8.9` resolves to commit
`2f9d81c968764f8f640f20b96be2d1777027e089`. The source archive is pinned in
`sources.sha256`; `feedbackd-device-themes.spec` uses upstream's Meson build
and enables all theme validation tests.

Validation completed:

- Local binary RPM and SRPM build; all 12 upstream theme tests passed.
- `rpmlint`: zero errors and zero warnings for the spec and binary RPM.
- Signed COPR RPM verified with the existing trusted key.
- Package installed in the existing aarch64 Phosh trial image; Sargo and
  Fajita validation passed. `bootc container lint`
  reported 10 passed, 1 skipped, and 4 existing image warnings. This was a
  package integration check, not a full image rebuild or publication.
- Installation through the final COPR allowlist passed in the aarch64 image.
  CI theme checks use `GSETTINGS_BACKEND=memory` without a graphical session.

For the phone's physical results and any live deployment, see the
[Sargo haptics record](../../devices/google-sargo/haptics.md).
On 2026-09-07, Sam confirmed the upstream 15 ms at 50% touch pattern is
perceptible. The signed RPM was then installed with `rpm-ostree --apply-live`
and staged for the next boot. At 08:54 AEST the temporary user theme was
removed and the original unset theme preference restored (`default`). Device
discovery selected the packaged Sargo theme, whose bytes match the physically
confirmed trial. This live package layer does not change the base image digest;
publication of an image containing the package remains pending.

To reproduce the SRPM build from the repository root:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
curl --fail --location \
  https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes/-/archive/v0.8.9/feedbackd-device-themes-v0.8.9.tar.gz \
  --output "$srpm_dir/feedbackd-device-themes-v0.8.9.tar.gz"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/feedbackd-device-themes/sources.sha256")
rpmbuild -bs \
  --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
  --define 'dist .fc46' --define 'fedora 46' \
  packages/feedbackd-device-themes/feedbackd-device-themes.spec
copr-cli build --nowait \
  -r fedora-rawhide-aarch64 -r fedora-rawhide-x86_64 \
  samcday/pocketfed "$srpm_dir/feedbackd-device-themes-0.8.9-1.fc46.src.rpm"
```
