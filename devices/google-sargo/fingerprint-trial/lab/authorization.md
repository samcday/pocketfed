# Post-reboot authorization check on test-sargo

After the successful [native credential creation](storage-recovery.md), this
separate disposable boot restores the completed lab credential from its private
host vault. It preserves the original intent, prior attempts and completed
record. It performs no Gatekeeper enrollment or credential replacement.

The fixed run `sargo-fingerprint-lab-authorization-20260911` uses handset
`99NAY1AZG1`, Linux UID 1234 and native Gatekeeper UID `0x700004d2`. The receiver
is the successful authenticated writer with only its exact run token changed;
the eight-group budget and permanent write-error latch are retained. Verification
may update Gatekeeper's secure bookkeeping, so this is not described as a
read-only operation.

The helper loads the completed record under the normal auth-store lock, writes
an exclusive attempt receipt, initializes and sleeps the sensor, imports the
wrapped authentication key, and obtains a fresh enrollment challenge from FPC.
It calls Gatekeeper verification once with the stored secret and handle. The
shared codec validates the returned HAT's size, challenge, password type and
handle SID. FPC then receives that HAT and must independently accept its HMAC.
No challenge value, handle, secret, key or token is logged or exported.

This check accesses no fingerprint database, collects no samples, and sends no
biometric enrollment command. FPC authorization is a prerequisite for the later
fprintd enrollment trial, not proof that a fingerprint has been enrolled.

Host and ARM64 lifecycle tests cover missing credentials, failed receipt sync,
backend and malformed-key errors, zero challenges, rejected verification,
rejected FPC authorization, cancellation and repeated-use refusal. Both builds
also pass the bounded receiver's protocol/MMC/identity/error tests. The exact
sources and binaries are recorded in [authorization-build.json](authorization-build.json).
The separate boot **passed**. The original retained credential verified with
Gatekeeper transport/status 0; the codec accepted its 69-byte HAT and FPC's
authorization command returned transport/dispatcher/command status 0. Wrapped
key import, challenge generation, sensor initialization and deep sleep also
returned 0. Three authenticated two-frame write groups completed with device
status 0 during verification. No database or sample operation was performed.

The automatic enforcing handoff and all secure-service shutdowns passed, with
no restarts. The original credential file was unchanged. The handset returned
to fastboot after an acknowledged SysRq reset before USB hosting stopped.
[authorization-result.json](authorization-result.json) contains the checksummed
report's metadata and recovery evidence, without secrets or tokens. This clears
the authorization dependency for the fprintd enrollment/cancellation trial.
