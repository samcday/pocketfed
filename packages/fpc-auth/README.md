# Native fingerprint enrollment auth broker

The current source implements the Google Pixel 3a (Sargo) native enrollment
backend. It attaches only to resident `keymaster64`, requires the inspected TA
version, sends the recovered stock GET/SET negotiation, and uses genuine
Gatekeeper enrollment/verification operations. The installed `0.2` package's
handshake passed on Sargo, but native enrollment returned secure status -30;
the missing RPMB service was subsequently isolated on test-sargo. A disposable
lab receiver with corrected read framing and bounded authenticated writes
allowed native credential enrollment to succeed, and the completed credential
was retained privately on the host. This is lab evidence; the daily phone's
failed attempt history remains unchanged. A subsequent disposable reboot verified
the retained lab credential, produced a structurally validated 69-byte HAT bound
to FPC's challenge, and received successful authorization from the FPC TA. These
results establish the lab authorization chain; fprintd enrollment and desktop
authentication still require acceptance testing.
The earlier `0.1` package had a disabled backend. The `0.3` candidate
adds per-boot HMAC startup and better failure diagnostics. Current `0.4` source
also fixes startup ordering found on test-sargo; it is not installed on the
daily phone yet.

Static systemd units are not enabled by installation. The broker and explicit
provisioning unit require the listener service, stop when its readiness lifetime
ends, and allow only public `/dev/tee0..15`. They require kernel `.11` or newer;
`.11` adds clearing of the kernel's temporary credential-bearing command buffer.
The userspace transport also clears its shared memory. An enforcing SELinux
policy permitting the actual broker/socket/device labels is still required.

The broker imports the wire header, Gatekeeper codec and QSEE transport from
`packages/fpc-qsee`. The packaging helper snapshots their exact bytes and
records SHA-256 hashes. There is no firmware extraction, privileged loader,
application-name fallback or automatic credential enrollment in this backend.
A repeated SET_VERSION success does not read back or replace configuration
previously stored by the loaded TA instance.

## Per-boot Keymaster startup

`pocketfed-keymaster-startup.service` is a static oneshot required by the broker
and provisioning units. The corresponding libfprint `1.4` source also requires
it before fprintd can open the sensor. It waits for the listener, common library
and FPC application loader. QSEE must have the recipient FPC TA loaded before
Keymaster can wrap an authentication key for it. Readiness is withdrawn when
either the listener or FPC loader stops. It does not start the broker socket or
provision a credential.

The helper repeats the exact checked GET/SET negotiation, then requests a
wrapped authentication key. A valid reply means the HMAC setup is already
usable, so it exits successfully without deriving another agreement. Only
transport success with the positively observed secure status -24 permits the
recovered GET_HMAC_PARAMETERS / COMPUTE_SHARED_HMAC sequence. This uses the
resident Qualcomm TA as its single participant, with only that TA's returned
64-byte seed/nonce pair. It checks the 32-byte sharing result and validates a
new wrapped-key reply before declaring readiness. It does not claim StrongBox
interoperability, authenticate a user, export raw keys, or create credentials.

A root-only runtime directory and nonblocking flock serialize startup. The
service can open only public TEE nodes, has no capabilities, cannot access
fingerprint/auth/QSEE state directories, and has no forced SCM stop deadline
or restart loop. Sensitive buffers are wiped; output contains only statuses
and validated lengths. Host tests cover already-ready idempotence, exact
negotiation and agreement framing, transport/status distinction, malformed
replies, cancellation and immediate stops without retries. The original
diagnostic agreement sequence passed on sam-sargo. In a disposable test-sargo
boot, the packaged helper returned `0xff000fff` when run before FPC loading;
loading FPC first made the same helper succeed with a validated 152-byte blob.
A second invocation returned already-ready without recomputing HMAC. Sensor
initialization, deep sleep and clean service shutdown also passed with SELinux
enforcing. These checks establish startup, not enrollment or authentication;
the full installed dependency chain still needs validation on sam-sargo.

## Callers and wire protocol

`pocketfed-fpc-auth --serve` only accepts one systemd socket activation descriptor
for `/run/pocketfed-fpc-auth/token.sock`. It verifies the Unix stream listener's
path, socket mode `0600`, and parent directory mode `0700`, owned by root. Each
accepted client must have UID 0 according to `SO_PEERCRED`. File permissions do
not replace that check. One request is processed at a time. The same exclusive,
nonblocking state lock covers CLI and broker transactions, including Keymaster negotiation and session cleanup.

One connection carries a 20-byte request and a 73-byte response. The request is
`FPCA`, version `1` as LE32, Linux UID as LE32, and nonzero challenge as LE64. The
response is a signed errno-style status as LE32 followed by a 69-byte HAT. Every
failure response has all-zero token bytes. The broker does not log request or
response content, credentials, handles, tokens, or secure-application responses.
The service accepts no provisioning operation over its socket.

Socket I/O shares one absolute five-second deadline, preventing a slow sender
from extending the timeout. SIGTERM/SIGINT cancel socket waits; disconnects fail
the transaction. Core dumps are disabled and sensitive buffers are explicitly
wiped. The stop flag is checked before each secure exchange, including between
GET_VERSION and SET_VERSION. A synchronous secure call can outlive the socket
deadline and is allowed to finish before its session and transaction lock are
released. Service stop has no forced timeout that pretends to cancel SCM.
Unsupported blocked-listener results and throttled/failed checks are not
retried automatically. Positive Gatekeeper throttle statuses map to `-EAGAIN`;
credential rejection maps to `-EACCES`.

## Explicit provisioning and its persistence rules

The root command is `pocketfed-fpc-auth provision LINUX_UID`. For a controlled
trial, use the static `pocketfed-fpc-provision@LINUX_UID.service` oneshot so its
kernel condition, listener ordering, device access and hardening apply. It is
never started by package installation or token requests. Direct CLI use requires
the same established kernel/listener/application prerequisites. Initial
provisioning mutates secure state and must use a new reserved native UID.

The shared `sargo_gk_uid_for_linux()` accepts Linux UIDs `0..0x00ffffff` and maps
them to `0x70000000 + uid`. This is an application-level reservation outside the
Android 12 framework and fake-user ranges identified during the Sargo audit.
**The TA does not reserve this namespace or offer a safe existence query.**
Initial provisioning therefore still requires an established policy that these
IDs have never been used for earlier native credentials. Lost, stale or restored
state cannot safely be treated as evidence that a secure-world UID is unused.
Reusing a Linux UID does not authorize replacement of its earlier credential.

Provisioning performs the verified handshake after obtaining exclusive state
and checking for existing records, before generating a secret or intent. It then:

1. Obtain the machine-wide lock and refuse any existing `uid-N.credential` or
   `uid-N.intent`, including malformed files and unexpected file types.
2. Generate a 64-byte random service credential with `getrandom()`. It never
   accepts or derives this credential from Sam's PIN, a command-line password,
   an environment variable, or a broker request.
3. Exclusively create `uid-N.intent`, write the UID mapping and random credential,
   and `fsync()` both file and state directory **before the enrollment call**.
4. Call the shared `sargo_gk_enroll_new()` once. The old-handle and old-password
   fields remain absent. These fields alone do not protect against UID collision.
5. On verified success, exclusively write and sync the secret and exact opaque
   58-byte handle to `uid-N.credential`, sync its directory entry, then remove and
   sync the intent. Neither file can be overwritten by this code.

Every ambiguous enrollment, write, sync or malformed response before the
completed credential and its directory entry are durable retains an intent or
partial credential. After that durable commit, failed intent removal or its final
directory sync returns the distinct positive
`AUTH_STORE_COMMITTED_CLEANUP_PENDING` result. The CLI reports that the credential
was committed, warns that cleanup needs review, and exits successfully. It does
not claim that the intent is still present: a failed final sync can leave it
absent now and possibly restored after a crash. The completed credential already
prevents another enrollment in either case.

No separate cleanup, deletion,
replacement, recovery or automatic retry command is implemented. Both files
existing after an interrupted commit also blocks use. **Do not remove an intent
to make provisioning succeed.** It preserves recovery material and prevents a
second enrollment from replacing a potentially valid secure credential. Recovery
must be designed separately with evidence about the actual secure state.

Verification loads the stored random secret and handle and calls
`sargo_gk_verify()` with the mapped UID and requested challenge. The shared codec
requires a 69-byte password HAT, matching challenge and matching handle SID. The
FPC TA must still verify the HAT's HMAC. Failed tokens are wiped before any reply.
Missing, incomplete or unsafe stored credentials are refused before backend
preparation, so a token request cannot initiate negotiation for unprovisioned state.

## State format and path checks

Production uses only `/var/lib/pocketfed-fpc-auth`. Every ancestor is opened with
`O_NOFOLLOW`, must be owned by UID/GID 0, and cannot be group- or world-writable.
The final directory must be exactly `0700`. The lock, intents and credentials
must be single-link regular files owned by UID/GID 0 with mode `0600`. Reads use
`O_NONBLOCK` to reject FIFOs without blocking. The global `.lock` file is empty;
its `flock()` is held for the entire transaction.

Intent and completed records are exactly 160 bytes:

| Offset | Size | Meaning |
| --- | --- | --- |
| 0 | 8 | ASCII `FPCAUTH1` |
| 8 | 4 | LE32 format version, `1` |
| 12 | 4 | LE32 kind: `1` intent, `2` complete |
| 16 | 4 | LE32 Linux UID |
| 20 | 4 | LE32 mapped Gatekeeper UID |
| 24 | 64 | Random service credential |
| 88 | 58 | Opaque Gatekeeper handle; all zero in an intent |
| 146 | 14 | Reserved, must be zero |

Truncated or oversized records, mismatched identities, malformed headers, zero
completed SIDs and unsafe metadata fail closed. The files contain sensitive
service credentials in plaintext and need the same protection in backups.

## Offline verification and packaging

From this directory run `make check`. Tests use temporary files and socketpairs;
they access no device or TA. Compile-time test seams permit temporary paths and
the test user's ownership. These seams are absent from the production binary.
The tests cover exclusive access, duplicate/incomplete provisioning, ownership
and permissions, symlink/hardlink/FIFO rejection, every truncated record length,
malformed state, interrupted writes, all three commit sync positions and unlink
failure, durable-commit cleanup warnings, root peer checks, wire errors,
zero-token failures, absent/mismatched Keymaster, cancellation and absolute
deadlines. Integration cases connect the real broker/store/codec through a
synthetic transport. Separate tests exercise the real QSEE adapter down to a
mocked Linux TEE boundary, including exact lengths, adjacent caller buffers,
status failures and full shared-memory erasure.
The tests need real `SO_PEERCRED` access: a sandbox denying that syscall must not
be mistaken for a failed peer-credential implementation.

To create a local SRPM, run
`python3 prepare-srpm.py /tmp/fpc-auth-srpm-UNIQUE_NAME` with a new staging path.
This only copies explicit source files and invokes `rpmbuild -bs`. It does not
submit, install, enable or start anything. Review the resulting source hash
manifest before coordinating any COPR build.

Before phone activation, use the COPR-built kernel with staging cleanup and the
listener package with readiness lifetime handling. Validate the enforcing
policy, namespace/provisioning workflow, resident app and actual secure storage
behavior during the controlled hardware trial. The currently validated masked
image predates this backend and does not contain it. Offline tests and package
builds do not establish end-to-end enrollment or fingerprint authentication.
