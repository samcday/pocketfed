# Bounded authenticated-storage recovery on test-sargo

The [frame probe](storage-probe.md) passed two MMC reads that total Gatekeeper's
24-sector table, then observed the TA's initialization write: two complete
frames, reliable group 2, and opaque RW field 0x100. Its read-only receiver
refused that write. This establishes the next dependency through a synthetic
invalid verification, without another enrollment request.

Sam explicitly authorized experimentation on dedicated test-sargo. This trial
lets the stock TA perform its authenticated storage writes while recovering
only the reserved native credential UID `0x700004d2`. It preserves the original
random secret and both failed-attempt histories. It requests no Android UID
operation, deletion, reset or key programming. Secure storage persists through
a disposable-root reboot; the host retains the intent and any successful
credential independently of that root.

The exact run is `sargo-fingerprint-lab-gatekeeper-storage-rw-20260911`, handset
`99NAY1AZG1`, with the accepted `.11` kernel and measured firmware. The new
receiver executable has only `--serve-authenticated-lab-trial`, checks the exact
serial/run/USB-root tokens before opening RPMB, and disables core dumps. Its
adapter forwards at most eight write groups and permanently refuses further
writes after a write transport error, unexpected write-result type or device
write error.
The existing MMC layer accepts authenticated data-write frames only; it has
no key-programming or retry operation. The codec retains frame bounds, device
capacity, reliable-group and message-type checks. It preserves the opaque RW
field as stock does. Keys/MACs are neither created nor modified by this proxy;
the stock TA and eMMC authenticate the opaque frames.

`lab_storage_recovery.py` requires both prior checksummed -30/no-handle results,
their retained host receipts, and the exact successful read/blocked-write
probe. It refuses an exported credential. It creates a fresh private
`authenticated-storage-recovery/` subdirectory, retains copies of that history,
and prepares an overlay carrying the original intent and export public key.
The old artifacts and launchers remain unchanged. Its seal includes the new
boot artifacts and all retained history; a separate exclusive host receipt is
fsynced before boot. `recover-storage-once.c` independently requires the prior
failure note and original intent, refuses a completed credential, writes its
own exclusive receipt, and calls Gatekeeper once. There is no automatic retry.

Successful export uses the already tested RSA-3072 OAEP/SHA256 helper. The
private key stays on the host, and the collector checks the returned record's
UID, format, SID and exact secret against the original intent before retaining
it. Logs contain status and framing metadata, never credentials, handles,
tokens, RPMB frame contents, addresses, counters, nonces or MACs.

Host and ARM64 tests passed for the corrected protocol/MMC shapes, writer
identity, group budget, error latch, combined dispatch, key-program refusal,
and single-use recovery lifecycle. Host tests also cover both required failure
histories, read-path proof, completed-credential refusal, changed sealed history
and one-use host launch. [storage-recovery-build.json](storage-recovery-build.json)
records the exact sources and binaries.

The sealed trial **passed**. Gatekeeper returned transport 0, secure status 0,
and a validated 58-byte handle. Both authenticated two-frame write groups
returned transport 0, response type 0x300 and device status 0. The helper
committed its credential successfully, and encrypted export was decrypted,
checked against the original retained secret and saved privately on the host.
All secure services stopped successfully with no restarts. SysRq reset was
acknowledged and exact fastboot identity verified before stopping USB hosting.
The consumed launch receipt and both earlier failed attempts remain retained.

[storage-recovery-result.json](storage-recovery-result.json) contains sanitized
metadata only. The enforcing handoff JSON was interrupted by an audit printk;
its separately recovered result does not rewrite the runner's automatic status.
This establishes native credential creation and authenticated storage, not HAT
issuance, fingerprint enrollment or desktop authentication. The next check
restores only this lab credential in a fresh disposable root, verifies it after
reboot, and asks FPC to validate the resulting enrollment authorization.
