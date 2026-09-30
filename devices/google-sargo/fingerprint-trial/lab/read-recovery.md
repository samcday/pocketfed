# Read-path recovery on test-sargo

The [first Gatekeeper trial](gatekeeper-trial.md) demonstrated an incorrect RW
version check in the prototype RPMB listener. The read request carried 0,
whereas the prototype required 2. Stock `librpmb.so` and Qualcomm/LK preserve
this field through their read/write handlers without using it as the INIT
negotiation version. The correction accepts only 0 or 2 and echoes the value;
all frame lengths, offsets, counts, address bounds and command checks remain.
The read-only receiver still rejects writes in both its protocol configuration
and transfer adapter. There is no key-programming path.

This is a deliberate separate recovery under Sam's explicit authorization to
experiment on dedicated test-sargo. It is **not** a repeat of the consumed
first-use launcher. The fixed handset is `99NAY1AZG1`, native Gatekeeper UID
`0x700004d2`, and run `sargo-fingerprint-lab-gatekeeper-rw0-20260911`. It reuses
the original retained random secret and export key. It does not create another
UID, delete history, replace an exported credential, or affect daily sam-sargo.

`lab_read_recovery.py` validates the original vault, first launch receipt and
checksum-verified failure report, including its single rejected read callback.
It keeps the original artifacts intact and creates `read-path-recovery/` below
the same private durable vault. The new fixture carries the original intent,
an explicit prior-failure note, a separately compiled fixed recovery helper,
and the corrected read-only receiver. A separate sealed launch receipt is
fsynced on the host before boot and refuses another launch. The helper requires
the prior-failure note, creates its own exclusive attempt receipt, and invokes
Gatekeeper once. It refuses a completed credential or a second recovery attempt.
Successful credential export uses the original tested RSA-OAEP path and host
validation against the retained secret. No credential or RPMB payload is logged.

The original one-use source and launcher are unchanged. This source only
exposes the fixed recovery experiment; it has no arbitrary UID or write option.
The accepted `.11` kernel, source image, firmware and FPC-before-Keymaster
startup sequence are reused. A read-only pass may still stop at a later storage
write or another unsupported request; that result must guide subsequent work.

Host and ARM64 tests passed for the corrected protocol, both write guards,
MMC command shapes and receiver dispatch. Recovery tests cover prior-history
absence/corruption/permissions, exact handset/run, failed receipt fsync, backend
failure, secure rejection, malformed handle, cancellation, success and replay
refusal. Host tests additionally exercise prior-result checks, completed-record
refusal, sealed artifact changes, preserved first receipts and one-use launch.
Build and source identities are in [read-recovery-build.json](read-recovery-build.json).

The recovery ran once and passed enforcing handoff in 64.73 seconds, but the
read callback still received status -1 and Gatekeeper still returned -30 with
no handle. No completed credential was exported. The version correction alone
is insufficient. The old logging cannot distinguish another frame-layout
rejection from an MMC transport error; do not infer a write failure from it.
The checksummed [result](read-recovery-result.json) preserves the observations.

The next receiver build has opt-in `SARGO_RPMB_DIAGNOSTICS` logging for envelope
sizes, the validation stage, transfer return code and reply status. It logs no
frame payload, address, counter, nonce, MAC or credential. Its write protections
are unchanged. No third enrollment attempt has been prepared or launched. The
next [storage probe](storage-probe.md) instead uses one deliberately invalid
verification request to reach the same initialization path without a real
credential or enrollment call.

UART acknowledged reset, the exact test serial returned to fastboot, then USB
hosting stopped. Both host attempt receipts and the original private intent
remain retained. Neither consumed launcher may be rerun.
