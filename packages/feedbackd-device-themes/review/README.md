# feedbackd-device-themes: packager self-audit

2026-09-07 — candidate `0.8.9-2`. These are preparation notes, not an official Fedora package-review approval. No blocking packaging issue was found in the manual checks below; an independent Fedora reviewer must make the review decision.

The spec builds a standalone `noarch` package from the unmodified [upstream signed release](https://sources.phosh.mobi/releases/feedbackd-device-themes/feedbackd-device-themes-0.8.9.tar.xz). Its SHA-256 is `b3892d7691c965ab8a126be3f2085763c58ab35ccd6e17e21a4a150656341d9f`. The archive's regular files match upstream tag `v0.8.9`, commit `2f9d81c968764f8f640f20b96be2d1777027e089`. The final spec invokes `%{openpgpverify}` first in `%prep`, with explicit Source2 keyring, Source1 detached signature and Source0 archive paths, before extraction. The [published 2025 signing key](https://sources.phosh.mobi/misc/signing-keys/signing-key-2025.asc) has primary fingerprint `0DB3932762F78E592F6522AFBB5A2C77584122D3`; signing subkey `63F6CCDF96229D09286B2AC325BF86524AFCC1E3` verified the release. This follows the current [source-verification policy](https://docs.fedoraproject.org/en-US/packaging-guidelines/#_source_file_verification). The key belongs in dist-git; the archive and detached signature belong in lookaside.

Manual findings:

- **License:** `GPL-3.0-or-later` agrees with the [upstream README](https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes/-/blob/v0.8.9/README.md), Meson metadata and copyright attribution. `COPYING` carries the RPM license flag. `README.md` and `NEWS` are documentation; runtime behavior does not depend on them. No bundled runtime libraries or executable code are shipped.
- **Payload:** Each final Rawhide, Fedora 44 and Fedora 43 RPM contains all 12 device themes. SHA-256 comparison confirmed that all 15 regular payload files, including the license and two documents, match the signed archive. The additional relative symlink `google,b4s4-sdm670.json` points to the packaged `google,bonito.json`. Files have appropriate root ownership and ordinary read-only data permissions.
- **Directories and coexistence:** Fedora's feedbackd owns `/usr/share/feedbackd` and its `themes` directory, and supplies `default.json`. The new package requires feedbackd and installs distinct device filenames, so it relies on directory ownership in its natural dependency chain. There is no duplicate default theme or daemon file. This matches the [directory-ownership rules](https://docs.fedoraproject.org/en-US/packaging-guidelines/#_file_and_directory_ownership).
- **Dependencies and architecture:** Runtime RPM requirements are `feedbackd >= 0.8.4` plus RPM internals. The same daemon floor supplies a suitable build-time validator; Meson, JSON validation and signature verification remain build dependencies. The floor covers separate keyboard events, consistent with [Debian's current control file](https://sources.debian.org/data/main/f/feedbackd-device-themes/0.8.9-1/debian/control) and its [0.8.5 dependency-change rationale](https://sources.debian.org/data/main/f/feedbackd-device-themes/0.8.9-1/debian/changelog). It is not an exact-version lockstep dependency. Hardware-specific names do not make the data architecture-dependent; `noarch` is appropriate. No package scriptlets, service changes or user-setting mutations are needed.

The final [Rawhide build log](validation-excerpts.txt) records one valid signature before extraction and 12 successful theme tests. Full FedoraReview rebuilt and installed the package successfully; [rpmlint](rpmlint.txt) reports zero errors and warnings. Fresh [Fedora 43](validation-excerpts.txt) and [Fedora 44](validation-excerpts.txt) Mock builds also verified the signature and passed all 12 tests.

Those stable compatibility builds allowed only `openpgpverify` from updates-testing. At this audit date, its backport has not reached their ordinary stable repositories, so an unmodified Fedora 43/44 review-service buildroot may fail dependency resolution until it does. This is a build-tool availability constraint; the resulting RPMs add no runtime dependency on testing packages.

The [FedoraReview template](fedora-review.txt) (whitespace normalized) leaves source verification pending with “gpgverify is not used.” FedoraReview 0.11.0's installed checker recognizes only the legacy macro and executable names, not `openpgpverify`; the final build logs demonstrate verification by the currently required tool. Its license scanner also requires manual interpretation for these data files. These template entries are explained by the manual checks above, not silently rewritten as official reviewer approval.

## Public candidate and reproduction

The [Bugzilla request draft](bugzilla-request.md) contains anonymous spec and
SRPM download URLs. Both downloads were compared byte-for-byte with the
locally reviewed artifacts. [COPR build 10956064](https://copr.fedorainfracloud.org/coprs/build/10956064)
succeeded on Rawhide x86_64 and aarch64, with build networking disabled.
Both architectures verified the signature and passed all 12 theme tests:

- [x86_64 full build output](https://download.copr.fedorainfracloud.org/results/samcday/pocketfed:custom:feedbackd-review/fedora-rawhide-x86_64/10956064-feedbackd-device-themes/builder-live.log.gz)
- [aarch64 full build output](https://download.copr.fedorainfracloud.org/results/samcday/pocketfed:custom:feedbackd-review/fedora-rawhide-aarch64/10956064-feedbackd-device-themes/builder-live.log.gz)

The candidate uses the `custom:feedbackd-review` side repository of the existing
PocketFed COPR. The initial `0.8.9-1` build remains the normal image feed and
live-phone deployment record. The COPR project does not run FedoraReview
itself; the full local FedoraReview run is recorded above. No Bugzilla review
request or automatic fedora-review-service run has been submitted.

Download the linked spec and SRPM into an empty directory, then run:

```sh
fedora-review --name feedbackd-device-themes --mock-config fedora-rawhide-x86_64 --checksum sha256
```

For a Fedora 44 compatibility build before the verifier reaches stable updates,
save this configuration as `feedbackd-f44.cfg`:

```python
include('/etc/mock/fedora-44-x86_64.cfg')
config_opts['root'] = 'feedbackd-device-themes-review-f44'
config_opts['dnf.conf'] = config_opts['dnf.conf'].replace(
    '[updates-testing]\nname=updates-testing\n',
    '[updates-testing]\nname=updates-testing\nincludepkgs=openpgpverify\n',
)
```

```sh
mock -r ./feedbackd-f44.cfg --enablerepo updates-testing --rebuild feedbackd-device-themes-0.8.9-2.fc46.src.rpm
```

Use 43 in place of 44 for Fedora 43. Only `openpgpverify` is admitted from
testing; build and runtime dependencies otherwise come from the standard
repositories. These compatibility builds do not prove that stable-only
review-service buildroots currently resolve the verifier. The backports are
tracked in [Fedora 44's update](https://bodhi.fedoraproject.org/updates/FEDORA-2026-753dbe2419)
and [Fedora 43's update](https://bodhi.fedoraproject.org/updates/FEDORA-2026-c3544ec192).
