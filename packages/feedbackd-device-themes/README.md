# feedbackd device themes

This standalone package installs the unmodified upstream 0.8.9 device themes.
Fedora feedbackd already provides the daemon, default theme, device discovery
and validation tools. This package supplies the separately released hardware
profiles and requires feedbackd >= 0.8.4 for the keyboard events they use.

The Phosh image explicitly installs the package through its existing COPR
allowlist. CI checks package presence and validates the Sargo and Fajita themes.
The initial image integration uses
[COPR build 10954637](https://copr.fedorainfracloud.org/coprs/build/10954637).
The Fedora review candidate is tracked separately in [review/README.md](review/README.md)
and [build.json](build.json).

feedbackd automatically selects a device theme using the device-tree
compatible string while the configured theme remains `default`. On Sargo,
upstream changes `button-pressed` and `key-pressed` from the generic 7 ms at
20% to 15 ms at 50%. Call and message vibration patterns are inherited.
This does not raise the driver's voltage limits or change user profiles.

The source is the signed upstream release archive. Its regular files match
release tag `v0.8.9`, commit `2f9d81c968764f8f640f20b96be2d1777027e089`.
Checksums cover the archive, detached signature and upstream signing key.
The unmodified public key is committed here; on import into Fedora dist-git,
keep the key in Git and upload the archive and signature to the lookaside cache.
The spec verifies the signature with `openpgpverify` before extracting sources,
uses upstream's Meson build and enables all 12 theme validation tests.

For physical results and live deployment, see the
[Sargo haptics record](../../devices/google-sargo/haptics.md).
Sam confirmed the 15 ms at 50% pattern is perceptible on 2026-09-07.
The initial signed `0.8.9-1.fc46` RPM was live-applied and staged for the next
boot, then the temporary user theme was removed and the original unset theme
preference restored. Automatic discovery selected the packaged Sargo theme.
The review candidate changes packaging and source verification; the theme
payload is byte-identical to that physically confirmed version.

To reproduce the SRPM build from the repository root:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
release_url=https://sources.phosh.mobi/releases/feedbackd-device-themes
for source in feedbackd-device-themes-0.8.9.tar.xz feedbackd-device-themes-0.8.9.tar.xz.asc; do
    curl --fail --location "$release_url/$source" --output "$srpm_dir/$source"
done
cp packages/feedbackd-device-themes/signing-key-2025.asc "$srpm_dir/"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/feedbackd-device-themes/sources.sha256")
rpmbuild -bs \
    --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
    --define 'dist .fc46' --define 'fedora 46' \
    packages/feedbackd-device-themes/feedbackd-device-themes.spec
mock -r fedora-rawhide-x86_64 \
    --rebuild "$srpm_dir/feedbackd-device-themes-0.8.9-2.fc46.src.rpm"
```

Fedora 43/44 currently need `openpgpverify` from updates-testing for this build;
see the review notes for the dependency's promotion status and the restricted
Mock configuration used for compatibility checks.
