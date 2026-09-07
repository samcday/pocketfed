Review Request: feedbackd-device-themes - Device-specific haptic and LED themes for feedbackd

Spec URL: https://download.copr.fedorainfracloud.org/results/samcday/pocketfed:custom:feedbackd-review/srpm-builds/10956064/feedbackd-device-themes.spec
SRPM URL: https://download.copr.fedorainfracloud.org/results/samcday/pocketfed:custom:feedbackd-review/srpm-builds/10956064/feedbackd-device-themes-0.8.9-2.fc46.src.rpm

Description:
Device-specific feedback themes adapt haptic and LED patterns to supported
phones. feedbackd selects the matching theme using the device-tree compatible
string and inherits other events from its standard theme. This packages the
separate upstream feedbackd-device-themes release as a noarch RPM; Fedora's
existing feedbackd package supplies the daemon and default theme.

Fedora Account System Username: samcday

Validation:
- Full local FedoraReview rebuild and installation on Rawhide succeeded.
  rpmlint on the spec, SRPM and binary RPM: zero errors and warnings.
- COPR Rawhide x86_64 and aarch64 builds verified the signed upstream release
  and passed all 12 theme tests: https://copr.fedorainfracloud.org/coprs/build/10956064
- Fedora 43/44 compatibility builds also pass, using only openpgpverify from
  updates-testing. Their normal stable buildroots need that build dependency
  to reach updates before an unmodified review-service build can succeed.

The spec uses openpgpverify as required by the current guidelines. FedoraReview
0.11.0's older source-verification check reports that gpgverify is not used;
the build logs show successful openpgpverify verification before extraction.
GPL-3.0-or-later was checked against upstream's licensing declaration and
COPYING. No daemon files, default theme or user settings are replaced.
