# Observe Gatekeeper storage without enrollment

After both preserved enrollment/recovery attempts received the same rejected
RPMB read, the next diagnostic uses verification with an entirely synthetic
invalid handle. No real credential, retained secret, PIN or biometric record
is read or copied into this fixture. There is no enrollment or deletion call.

Private static analysis of the already authorized SAM.008 Keymaster program
places the verify handler at 0x9c00. It checks the supplied handle length is
58 bytes (0x9de8), hashes the supplied password, copies the supplied handle,
and calls record acquisition at 0x9ee0 before verification at 0x9f00. Record
acquisition calls storage initialization at 0xf998. Thus a structurally valid
request with an all-zero invalid handle can exercise the same initialization
path without requesting a new credential. This is a code-derived prediction;
the actual callback remains to be measured. Initialization can attempt writes,
which the receiver refuses; verification is not claimed universally stateless.

`storage-probe.c` fixes the handset to `99NAY1AZG1`, the run to
`sargo-fingerprint-lab-storage-probe-20260911`, and the same reserved lab UID
`0x700004d2`. It supplies 58 zero handle bytes, one zero password byte and test
challenge 1. It performs one call, records status only, wipes any token output,
and treats an unexpected successful verification as an error. A guest receipt
prevents another invocation; `boot-storage-probe.py` writes an exclusive durable
host launch receipt before executing the normal liveboot runner. The old
credential attempt receipts and private vault are not modified.

The existing FPC/Keymaster startup order and read-only receiver remain. The
receiver is built with `SARGO_RPMB_DIAGNOSTICS`, recording envelope counts,
lengths, offsets, version field, validation-stage label and transfer status.
It does not record RPMB addresses, counters, nonces, MACs, frame contents or
credential material. Both write guards are unchanged, and this helper has no
direct RPMB access. The unit keeps real credential stores inaccessible.

Host and ARM64 tests passed for the fixed synthetic request, exact identity,
cancellation, receipt/backend/transport failures, rejection observation,
unexpected-success refusal, and one-use guard. Instrumented receiver tests also
passed on both architectures. Source and binary hashes are recorded in
[storage-probe-build.json](storage-probe-build.json).

The live diagnostic passed enforcing handoff in 65.15 seconds and reproduced
the predicted storage callback. It reported command 0x102, count 34, declared
length 8704, offset 24, version field 0, and failure stage `read-length`.
No MMC transfer was attempted. The value 8704 is 34 × 256 payload bytes, not
the size of the single 512-byte request frame. Gatekeeper returned -30, as
expected while this read is rejected. All services then stopped cleanly, and
the phone returned to fastboot before USB hosting was stopped. The
[checksummed result](storage-probe-result.json) records the outcome.

The corrected codec accepts the observed payload-length convention as well as
the prior single-frame encoding. It bounds the physical 512-byte input frame
separately, snapshots only that frame, and still returns complete 512-byte
response frames. A one-block payload length near the end of shared memory is
explicitly tested to prevent an out-of-bounds physical-frame read. Write
protections remain unchanged. A separate `storage-frame-probe` run will use
the same synthetic invalid verification to test the corrected read path.
No third enrollment or recovery request is being prepared.

The subsequent frame probe passed enforcing handoff in 64.94 seconds. Reads
of 34 and 14 complete frames both reached the MMC transport and returned 0;
these total the 24 logical 512-byte sectors in Gatekeeper's table initializer.
The TA then requested a two-frame write (length 1024, offset 24, reliable group
2, RW field 0x100). The receiver rejected it at the envelope version check;
its independent write guards were also still disabled. A final one-frame read
completed, Gatekeeper returned -30, and all services stopped cleanly. See
[storage-frame-probe-result.json](storage-frame-probe-result.json).

This also establishes that restricting the RW field to 0 or 2 was unwarranted:
the stock and LK handlers preserve it without interpretation. The corrected
codec follows that behavior while retaining all bounds, frame-type checks and
the independent write opt-in. Tests cover the observed 0x100 two-frame request,
write refusal, explicitly authorized forwarding and opaque field preservation.
No authenticated data write has yet been forwarded on either handset.
