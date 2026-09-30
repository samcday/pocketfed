# Gatekeeper secure-storage investigation

The daily-phone history below is retained. Work has since moved to dedicated
test-sargo, where the user authorized disposable liveboot experiments and a
real native credential trial. That trial loaded FPC/Keymaster successfully and
observed a read callback with RW version field 0; the prototype rejected it
because it incorrectly required 2. The codec now accepts the observed 0 and
documented 2, preserving the field as the stock and LK RW handlers do. Host and
ARM64 tests pass. This does not change INIT handling or enable data writes.
See the [lab result](lab/gatekeeper-trial.md) and separately guarded
[read-path recovery](lab/read-recovery.md). No new daily-phone attempt has run.

The approved one-time native recovery returned transport 0, secure status -30,
and no credential handle. That failure is preserved; the recovery tool must not
be run again or its receipt removed. The immediate investigation is the missing
RPMB listener, not another enrollment attempt.

## Evidence and its limits

| Layer | Evidence | Remaining uncertainty |
| --- | --- | --- |
| Sensor and FPC TA | Real touch accepted; empty native fingerprint database created and reopened | Enrollment and matching require a valid authentication token |
| Keymaster HMAC | Per-boot single-participant setup produced a validated wrapped key | Still needs durable service integration for subsequent boots |
| Gatekeeper | Recovery reached the TA and returned -30 | This status covers record acquisition failure; allocation, storage initialization and table exhaustion are not distinguished |
| QSEE userspace | Installed daemon registers FS 10 and GPFS 0x7000 | RPMB 0x2000 is absent |
| Linux/eMMC | Counter/status read returned transport 0, response type 0x0200, device status 0 and matching nonce | This diagnostic does not authenticate the response MAC or test authenticated reads/writes |

The counter diagnostic used only two fixed MMC commands in a single
`MMC_IOC_MULTI_CMD`: CMD25 carrying RPMB request 2, then CMD18 receiving one
frame. Sending a read-request packet is required by the eMMC protocol. No
data-record request, authenticated data write or key-programming request was
constructed. It logged neither counter value, MAC, nonce nor stored contents.

The phone reports 16 MiB RPMB capacity, enhanced RPMB support, and generic
`rel_sectors=1`. The stock library computes 32768 capacity units of 512 bytes
and advertises 32 reliable frames when enhanced RPMB is supported. Individual
RPMB frames are 512 bytes with 256-byte data payloads. Write grouping comes from
the trusted request and can be less than the maximum advertised capacity.

## Protocol sources

The open Qualcomm/LK implementation in the local lk2nd checkout (commit
`4a88d4cc9d6da226a90e55f2a0e66f7179a0b79b`) documents listener 0x2000,
25 KiB shared memory, initialization 0x101, read 0x102 and write 0x103.
Reference files are `platform/msm_shared/rpmb/rpmb_listener.c`, `rpmb.c`,
`rpmb_emmc.c`, and `platform/msm_shared/include/rpmb.h`.

Private analysis of this device's stock `/lib64/librpmb.so` (29488 bytes,
SHA256 `63471d0417b101723e6d99ac58de71f0ef57281f4f705a2c8880d18a64bc0bf2`)
confirms the version-2 layout and request-specified write grouping. Its
legacy vendor MMC ioctl is replaced by the current kernel's upstream multi
command interface, whose counter-read path has been measured on the device.
The copied library remains in `/tmp/sargo-fingerprint-private`; it is not a
runtime dependency or repository payload. No credential stores were copied.

Stock also supports older initialization formats and partition-configuration
request 0x104, consulting `/system/etc/rpmb_sec_parti.cfg`. The experimental
codec currently fails those unsupported requests. We have not established that
the existing Gatekeeper partition will need that configuration callback. Do
not invent an empty partition configuration or create replacement partitions
to make initialization pass.

## Prepared code

`rpmb-protocol.c` is an experimental bounded codec. It snapshots request frames
before overwriting shared memory, checks lengths/offsets/counts, constrains
write batches to the device capability, and refuses key programming. Data
writes require an explicit boolean opt-in. It forwards opaque frames without
generating keys or MACs; secure firmware and the storage device remain
responsible for authentication. Device errors stop further write groups and
are returned for secure-world validation. Transport errors discard partial
responses, stop further groups, and never retry.

`rpmb-mmc.c` builds only the fixed read and authenticated-write transaction
shapes. Writes use CMD25 with the reliable-write bit, a fixed result-read
request, then CMD18. It separately refuses key programming and retries.
It expects an already validated RPMB descriptor; it has no standalone device
discovery, service integration, or invocation path.

`rpmb-counter-check.c` is the separate fixed live diagnostic. Its device path,
observed character-device numbers and root0600 checks deliberately bind it to
this trial. Do not use it as a generic device-discovery utility.

All three synthetic test programs passed both host and ARM64 container runs
with `-Wall -Wextra -Werror`. Tests cover request/reply overlap, malformed and
overflowing envelopes, address limits, explicit write enablement, key-program
refusal, command shapes, grouped writes, and immediate stopping after device
or transport errors. Host sanitizer linking was unavailable because the local
ASan/UBSan libraries are missing; no sanitizer result is claimed.

## Next hardware gate

The proxy binary has been copied to the private runtime trial directory, but
has **not** been activated, registered with QSEE, or used to access RPMB records.
Before any credential recovery:

1. Integrate the codec into the existing single QSEE receiver, retaining FS/GPFS
   and their lifetime handling. A second independently receiving daemon is not
   compatible with the current kernel's single-receiver interface.
2. Resolve any observed version/partition configuration differences without
   fabricating responses. Validate startup, clean withdrawal, shared-memory
   sizes and service permissions with writes disabled first.
3. Review the exact authenticated storage operations and prepare a separately
   guarded recovery that preserves the original intent and first receipt.
   The previous recovery's approval cannot authorize a repeat.
4. After a usable Gatekeeper credential exists, test GNOME Control Center
   enrollment, matching and nonmatching fingers, persistence, and the actual
   Phosh/Phrog authentication paths.

The existing listener/loaders remain active; fprintd and authentication sockets
remain masked. Normal PIN login remains available. No touch or USB action is
currently pending from Sam. The broader fingerprint goal is unfinished.

## Combined receiver prepared; activation awaiting approval

`rpmb-supplicant.c` now combines the existing FS/GPFS handlers and transport
from qsee-supplicant commit `de09a5427cb6f114b91a29b9c7f8f8d1cb53f752` with
the experimental RPMB codec. It has only `--serve-read-only`: both the codec
configuration and the independent transfer adapter refuse data writes.
Startup validates this phone's exact eMMC capability metadata and root0600
character device 504:0. It uses one registration lifetime with no retry and
waits for all three listeners before announcing readiness. Callback logs
contain only known command fields and status, never frame payloads.

Host and ARM64 tests passed for combined dispatch, page-rounded shared-memory
capacity, write refusal through both guards and stopping-state refusal. The
ARM64 binary is `/run/sargo-fingerprint-trial/rpmb-supplicant-ro`, SHA256
`9a5208af3d26b7575b7db5a89025419f55941efe8b0385a99b7df5f1017e186d`.
The local build manifest is `/tmp/sargo-fingerprint-live-v3/rpmb-ro-manifest.json`.

`start-rpmb-read-only.py` is the exact prepared activation. It validates the
kernel, preserved recovery-file metadata, masked authentication services, old
override and binary hash; acquires the fingerprint device lock; then saves the
old override before stopping QSEE and its app loaders. It starts the combined
read-only daemon and existing loaders under the original service hardening,
with no restart loop or forced stop deadline. It neither enrolls nor recovers
a credential. A runtime attempt receipt prevents accidental repetition.

Automatic approval review rejected **execution**, citing disruption risk from
changing shared secure-service state without explicit approval for this exact
mutation. No activation receipt, stop, override replacement, or registration
occurred. Sam has been asked to approve the prepared operation. The copied
binary and script remain inactive; the existing daemon and loaders remain in
place. Approval is the currently pending user action; no touch or USB action
has been requested.
