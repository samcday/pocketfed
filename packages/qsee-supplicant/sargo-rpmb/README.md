# Optional Sargo secure-storage listener

Local candidate, not installed or activated. The separate `qsee-sargo-rpmb`
executable combines FS, GPFS and RPMB listeners in one registration lifetime.
It reuses the frame codec and MMC transport that passed lab Gatekeeper
enrollment, post-reboot verification and FPC enrollment-token authorization.
It does not provision credentials or initiate any secure storage requests.

Root must explicitly select `--serve-read-only` or `--serve-authenticated`.
The device tree must identify `google,sargo`; the opened character device must
match the kernel's named `mmcblk0rpmb`, its mmcblk0 card parent and the sysfs
character-device identity. The inspected card geometry is required. There is
no arbitrary device path, raw command passthrough, key programming, MAC
generation or automatic replay of an MMC transaction.

The codec preserves the opaque RW field and accepts the observed read payload
length separately from the full physical request frame. It bounds requests,
response capacity, frame types, data ranges and reliable write groups. Input
and output share memory, so the request is copied before the response is
cleared; transient frame copies are wiped afterward. Secure firmware and the
RPMB device validate the authentication data. This process does not hold the
RPMB key or claim to authenticate frames independently.

Compared with the one-use lab receiver, this candidate removes the exact boot
token and eight-group lifetime limit. It retains a process-lifetime write-failure
latch: an ambiguous transport result, unexpected result type or nonzero device
write status refuses every subsequent write; reads remain available. A new
process resets that latch, so the supplied service template disables automatic
restart. Review the original failure before any explicit restart. Normal
provisioning still preserves intents and refuses automatic credential recovery.

The RPM installs the executable and this documentation, including a
`90-sargo-rpmb.conf` template. It does not copy that template into a systemd
drop-in directory. Applying it later replaces qsee-supplicant's ExecStart while
preserving its state directory and existing dependent service names. It retains
the previously exercised CAP_SYS_ADMIN boundary, disables forced stop deadlines
and core dumps, and requires the `.11` kernel ABI. No firmware is included.

Before daily-phone deployment: run the packaged executable on the dedicated
test device with the real dependent service chain, retain enrollment records,
verify matched and unmatched fingers, restart/reboot and recheck persistence,
and verify orderly service shutdown. The receiver must not be replaced while
dependent TAs still use its registrations. Production SELinux/device access and
the daily phone's incomplete native credential need separate validation.

`source-origin.json` records the imported lab bytes before the package-specific
changes. The package source archive includes hashes of the final files. Build
tests cover the inherited codec/MMC boundaries, named-device checks, read-only
mode, more than eight successful synthetic writes, write-failure latching,
reads after failure, key-program refusal and stop handling. Synthetic tests
never open the real RPMB device or submit hardware commands.
