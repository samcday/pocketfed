# Touchscreen first boot

Tracking: [PocketFed #47](https://github.com/samcday/pocketfed/issues/47).

Factory images keep locale, timezone and hostname unconfigured. The base
[noninteractive firstboot policy](../base/firstboot.md) lets systemd finish
initialization without a console, while continuing to consume credentials
supplied by fastboop or another provisioning environment.

Phrog starts `pocketfed-first-boot` through its `first-run` setting. The wrapper
queries systemd's user database for regular accounts, including homed users.
If one exists, it ensures AccountsService knows the account and returns to
Phrog. Otherwise it runs phosh-first-boot. Phrog waits for homed to finish
starting before making this decision. This covers both pre-provisioned images
and interruption after account creation but before the final setup button.

The [phosh-first-boot package](../packages/phosh-first-boot/) supplies the
assistant, setup policy and first-session importer. Fedora ships the homed
service in `systemd-udev`; there is no need for a package named systemd-homed.
The Phosh layer explicitly enables homed and its authselect PAM feature.

The first account uses homed's directory storage and Fedora's `wheel` group.
Selected keyboard settings are handed to the first graphical session through
`/var/lib/phosh-first-boot`, so a reboot before login does not discard them.
Phrog's own writable dconf state lives under `/var/lib/greetd` and is created
by tmpfiles on a new OSTree deployment.

The assistant keeps its window visible until setup finishes. Account creation
commits the selected settings: Back is disabled while creation is pending and
after the account exists, but becomes available again if creation fails.
The timezone picker searches city names anywhere in the displayed zone name.

## Verification

CI runs `base/test-firstboot` inside the image to exercise real systemd
credential handling with fresh and configured temporary roots. It also runs
`phosh/test-firstboot-image` to check installed programs, service enablement,
PAM integration, the greeter entry point and writable state.
It also checks paths embedded in the installed assistant. The image pins the
tested COPR release so a cached build cannot silently retain an earlier RPM.

Hardware acceptance requires a newly installed userdata image without a
regular account, locale/timezone credentials or console input. Check:

1. Factory boot reaches the assistant automatically.
2. Language and timezone changes persist, and failures can be retried.
3. Account creation produces a regular user with admin access.
4. The account appears in Phrog and can enter Phosh.
5. Reboot uses normal login and preserves the chosen settings.
6. Restart before account creation resumes setup; restart after creation
   offers the existing account instead of asking for another one.

UART may record boot progress, but answering its prompts invalidates the
unattended first-boot check. SSH keys used for test observation are not a
substitute for a regular account or a firstboot credential.

Device results and package/image provenance are recorded in the tracking issue.
