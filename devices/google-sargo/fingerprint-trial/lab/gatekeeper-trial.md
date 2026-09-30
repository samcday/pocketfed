# One Gatekeeper storage diagnostic on test-sargo

This trial uses only dedicated handset `99NAY1AZG1`, the accepted `.11` kernel,
the measured lab firmware and the verified FPC-before-Keymaster startup order.
The read-only RPMB receiver is unchanged: its protocol and transfer layers both
reject data writes and key programming. A first Gatekeeper enrollment request
for reserved native UID `0x700004d2` (Linux UID 1234) will exercise the storage
initialization path. No Android UID, fingerprint enrollment, deletion or bulk
reset is exposed. The TA has no safe existence query; the reservation and this
lab's first-attempt history provide the namespace guard, not a claim that the TA
proved the UID absent. The daily phone's UID and recovery records are excluded.

## Durable recovery material

The Linux overlay is disposable while secure-world state may persist.
`lab_vault.py init` therefore creates a new 0700 directory on the host's
persistent filesystem, generates a 64-byte random service credential and writes
its 160-byte intent with O_EXCL, file fsync and directory fsync. It also creates
a private RSA-3072 export key. Only the new lab intent and public key enter the
private fixture; no state from either handset is copied into it. The vault and
all generated fixture/run artifacts stay below `out/private/`.

`lab_vault.py seal` records the prepared run identity and manifests.
`lab_vault.py boot` checks those seals, the exact serial, USB-root mode and
accepted kernel bundle, then durably reserves the single host launch before
executing the existing liveboot runner. An attempted launch is never erased or
retried automatically, including if boot fails before reaching userspace.
**Do not bypass this launcher with a direct `run.py boot` or re-create the
fixture under another run ID to repeat enrollment.** The guest helper also
checks the exact serial/run, locks the credential store, validates the retained
intent and writes an exclusive attempt receipt before calling Gatekeeper once.
Its receipt is not claimed to survive a disposable-root reboot; the host receipt
provides that guard. Intent and attempt history survive any uncertain result.

The controller verifies the public-key hash and successfully encrypts a dummy
record before secure-service startup. If a credential is committed, its exact
160-byte record is encrypted with RSA-OAEP/SHA256 and sent as ciphertext in the
checksummed UART reports. The private export key never goes to the handset.
The host decrypts privately and accepts only the expected kind, UID, nonzero SID
and the exact secret retained in the original intent. No credential/handle/HAT
bytes or RPMB frame contents are logged. A power loss between secure enrollment
and host collection can still leave an ambiguous outcome; the retained secret
supports deliberate recovery, not automatic replacement.
The controller and its export child disable core dumps before reading the
intent or completed record; the Gatekeeper service separately sets LimitCORE=0.

## Source and validation

- `enroll-once.c`: fixed-UID, single-attempt helper using the existing store,
  Keymaster backend and Gatekeeper codec; no new production recovery interface.
- `trial-gatekeeper.py`: serial-bound startup, export preflight, one service
  invocation, status-only callback reporting and encrypted result export.
- `prepare-enroll-overlay.py`: derives the private overlay from the accepted
  ordered lab overlay, retaining the original service masks and receiver.
- `lab_vault.py`: private host creation, sealed one-use launch and collection.
- `encrypt-record.c`: fixed 160-byte input / 384-byte RSA-OAEP output using the
  image's OpenSSL 4 library. It has no TEE access or private key.

Host and ARM64 helper tests passed: exact identity binding, missing intent,
failed receipt fsync, backend failure, secure rejection, malformed handle,
cancellation, successful commit and refusal to repeat. Real host OpenSSL tests
passed encryption/decryption, corrupted ciphertext and wrong UID/secret/kind
rejection, private-file checks, changed launch seals and one-use reservation.
The ordinary RPMB codec/MMC/combined-receiver tests were already accepted; this
trial uses the same read-only receiver binary without modification.

Host inspection found the first prepared image had no `openssl` CLI, before
any boot or launch reservation. That unbooted preparation was archived inside
the private vault, preserving its evidence and the unchanged original intent.
The corrected fixture includes the small library-based export helper. Real
ARM64-helper/host-decryptor interoperability passed, including rejection of
short/long input and invalid keys. Sealing also verifies the helper and
`libcrypto.so.4` are present in the exported EROFS before launch.

Preparation and test success do not establish that the live storage callbacks
work. Record the actual receiver command/version/status and Gatekeeper result
before changing protocol support or considering authenticated writes. A failed
or uncertain attempt must preserve the host intent and launch receipt.

## Execution approval

Automatic approval review rejected the attempted launch before creating a host
process or launch receipt. Its stated reason was that a real Gatekeeper
enrollment may persist secure-world credential state, and general investigation
and test-device access did not explicitly authorize this specific mutation.
Sam then explicitly approved the trial and broad experimentation on test-sargo:
"this device is yours to do with as you will :D yes approved". The sealed trial
ran once; its host launch receipt is consumed and retained. This is separate
from the old, unexecuted daily-phone RPMB service replacement proposal.

## Live result

The enforcing `.11` USB-root handoff passed. Firmware staging, all listeners,
cmnlib64, FPC and Keymaster startup succeeded. Gatekeeper returned transport 0,
secure status -30 and validated handle length 0. No completed credential was
created or exported. The receiver observed one read callback: command 0x102,
34 frames, version field 0; its formatted reply had status -1. Both write
guards remained disabled. See [gatekeeper-result.json](gatekeeper-result.json).

The prototype incorrectly required version 2 on RW requests. The stock
`librpmb.so` dispatch at 0x4c50–0x4d28 does not check that field and preserves
it in the response. The local Qualcomm/LK reference does the same. INIT version
negotiation is separate. A narrow codec correction accepts RW field 0 or 2 and
preserves it, retaining bounds and command checks. Its live acceptance remains
pending; other request fields were not captured in this run.

UART acknowledged SysRq reset, fastboot identified the exact test handset, and
only then was USB hosting stopped. The original intent, private export key,
launch receipt and checksummed result remain in the durable private vault.
Any later deliberate recovery must retain and refer to this history; this
one-use launch must never be reused.
