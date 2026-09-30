# Sargo Gatekeeper enrollment authorization

The inspected stock `keymaster_b` image has SHA-256
`8f800f36d6eef63373dc502462c5f52d1d779dd078e0ae429108ea86fcbb261a`.
The user authorized private local analysis of it and the stock Gatekeeper HAL.
Neither proprietary code nor credentials are included here. These observations
are specific to this firmware; no Gatekeeper command has been sent to the phone.

## Established format

The stock Gatekeeper constructor selects security level 1 (TEE). Enrollment
uses command `0x1001`, verification `0x1002`; this is the older fixed-field
protocol, not the later Qualcomm CBOR format. All request integers are little
endian. Both headers occupy 32 bytes, followed by variable payloads. Offsets
are relative to the start of the request.

| Offset | Enroll | Verify |
| ---: | --- | --- |
| 0 | command, u32 | command, u32 |
| 4 | Gatekeeper UID, u32 | Gatekeeper UID, u32 |
| 8 | old handle offset/length, u32 pair | challenge, u64 |
| 16 | old password offset/length, u32 pair | handle offset/length, u32 pair |
| 24 | desired password offset/length, u32 pair | password offset/length, u32 pair |

The native codec exposes fresh enrollment only, with zero old-credential pairs.
The stock HAL and native codec append payloads without padding. A 58-byte
handle puts the verify password at offset 90. Fresh-enroll request length is
32 + password length; verify request length is 32 + 58 + password length.
Response capacity is 0xa000 minus that exact request length. The transport's
separate memory-reference placement does not alter this secure-world split.

Both replies contain signed status at 0, blob offset at 4, and blob length at
8. Successful enrollment returns a 58-byte opaque handle; successful verify
returns a 69-byte HAT. The inspected TA places each blob at offset 12. Negative
status is failure; positive status is a throttling interval, never success.
The codec preserves secure status and transport errors separately and never
retries a rejected credential automatically.

The handle contains an authenticated secure user ID at byte 1. The HAT must
have version 0, the requested nonzero challenge, the same secure user ID,
and network-byte-order password authenticator type 1. Its timestamp is also
network order. These structural checks do not verify the MAC: the FPC TA must
accept the genuine hardware-signed HAT before enrollment can begin.

## Exact stock negotiation: offline codec only

The approved stock `libkeymasterdeviceutils.so` has SHA-256
`39a8184c331d5c7f0fa5c0e02d50499edfa2b905f8ce097732f23a7b774a5bc2`.
Its constructor at 0x22d8 performs these exchanges, clearing the 0xa000-byte
shared buffer before each:

| Command | Request length | Response capacity |
| --- | ---: | ---: |
| GET_VERSION 0x200 | 4 | 40956 |
| SET_VERSION 0x207 | 24 | 40936 |

The response immediately follows the request in stock shared memory. The
GET_VERSION response contains status followed by four little-endian words
`[4, 0, 4, 165]`. The constructor's own labels establish them as TA API major,
TA API minor, TA major and TA minor, respectively.

The full SET_VERSION request is six little-endian words
`[0x207, 4, 5, 4, 5, 0]`. The constant block at ELF offset 0x1170 supplies the
first four words; constructor 0x252c writes the next 5, and the final word
remains zero after clearing. Request offsets 12/16 are HAL major/minor.
Semantic labels for offsets 4/8/20 are not independently established; their
exact values are. Offset 20 is **not** the constructor's security-level value 1.
Both transport return and secure status must be zero.

`qseecom_dev_init()` at 0x263c only clears/returns the shared buffer, and
`send_cmd()` at 0x28ec forwards pointer/length arguments unchanged. The separate
`append_to_buf_roundup()` helper rounds to four bytes, but stock Gatekeeper
calls the non-rounding `append_to_buf()` at 0x2014. No padding is added by the
inspected QSEECom API when both pointers already address its shared buffer.

The callback-based `sargo_km_negotiate()` helper first checks all four exact
GET_VERSION fields, then sends the fixed SET_VERSION request once. An
unrecognized version or any secure/transport error stops the sequence, clears
the output version and performs no retry. Response decoders reject truncated
successful replies, preserve nonzero secure statuses, and decode unaligned
little-endian data without native integer loads. Response capacity is larger
than the returned fields, as in stock; trailing capacity is not a framing error.

The helper puts an error sentinel in the caller response before exchange. This
only detects callbacks that leave that output untouched. The real kernel
zero-fills its own response staging and copies it back; the sentinel cannot
prove the TA wrote status zero. GET's exact version check rejects a zero-only
reply, while SET has only a status field, matching the recovered protocol.

**SET_VERSION takes effect once per loaded TA instance.** The TA checks its
configuration flag before reading request length or fields. Every stock C++
constructor sends both exchanges, but subsequent SET calls silently retain
the first configuration. GET_VERSION reports TA version constants, not the
stored client settings. A successful repeated SET therefore neither repairs
nor verifies prior configuration, and reconnecting is not proof of a fresh TA.

This is offline preparation only. The helper opens no transport or device,
loads no TA, and is not wired to the live auth backend. Current residency,
configuration and listener readiness still require separately controlled
validation. The submitted probe COPR 10973664 contains earlier source and
**does not include these codec changes**; no replacement RPM was submitted.

## Native credential reservation

Gatekeeper shares one numeric UID table. Fresh enrollment with no old handle
can replace an existing matching record; it does not prove that UID is unused.
There is no safe per-UID existence query in the recovered command table.

The native codec accepts only `0x70000000 + LinuxUID`, with LinuxUID no larger
than `0x00ffffff`. This is an application reservation, not a secure-world
namespace. It excludes ordinary Android 12 framework IDs: `UserManagerService`
allocates user IDs below `Integer.MAX_VALUE / 100000` (21474), and synthetic
password credentials use the user ID or `100000 + userId`.
[Android 12 user allocation](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-12.1.0_r1/services/core/java/com/android/server/pm/UserManagerService.java),
[UID range](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-12.1.0_r1/core/java/android/os/UserHandle.java),
[synthetic password mapping](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-12.1.0_r1/services/core/java/com/android/server/locksettings/SyntheticPasswordManager.java).

The broker must separately prevent native ID reuse: explicit provisioning,
root-only durable credential state, an exclusive durable intent record before
the TA mutation, and no automatic reenrollment after missing state or an
ambiguous failure. A copied high UID is not proof that no other native software
has used it. Delete-user/delete-all must never serve as discovery operations.

The proposed native credential is a random broker-owned value, not Sam's PIN.
Only a root client authorized by fprintd's normal enrollment policy may request
a challenge-bound token through [auth-broker.h](auth-broker.h). A valid biometric
match still comes from the FPC TA and requested libfprint gallery. No enrollment
or token issuance has been demonstrated on the phone.
