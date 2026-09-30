# Remaining Keymaster integration work

The native backend is now implemented in `auth-backend.c` and wired into the
broker and explicit provisioning command. Host and ARM64 tests pass through the
real codec/transport with synthetic TEE replies, including the exact stock
buffer splits and erased shared memory. The `0.2` source RPM is submitted for
ARM64 COPR; `backend-build.json` records its source and results. No real
credential, token or device operation has been attempted.

The backend attaches only to resident `keymaster64`; it does not extract or load
firmware. The static service and provisioning units order after and bind to the
listener service, permit only public TEE nodes, and require kernel `.11` or
newer. Their activation and SELinux integration still need the controlled trial.

The current fingerprint trial firmware plan contains the FPC TA and `cmnlib64`.
It does not yet contain `keymaster64` extraction or loader ordering. The existing
legacy QSEECOM client open operation attaches to an application that is already
loaded. It does not make an absent Keymaster application available.

First establish application presence and identity through the backend's
application lookup/attach mechanism during the authorized trial, without sending
Gatekeeper or negotiation commands. A boot argument containing `keymaster1` is
not proof that `keymaster64` is resident. If lookup confirms the correct existing
application, use that identity; do not load a second image speculatively. If it
is absent, coordinate explicit firmware packaging and loader dependencies before
implementing service activation. Token requests must not provision credentials
or implicitly extract/load a TA.

The already authorized private `keymaster_b` partition inspection establishes:

- ELF64/AArch64 with eight program headers.
- Partition SHA-256:
  `8f800f36d6eef63373dc502462c5f52d1d779dd078e0ae429108ea86fcbb261a`.
- First segment (`b00`) size `0x200`; hash segment (`b01`) starts at `0x1000`
  and has size `0x1a28`.
- The highest segment end is `0x35e69`, within a 512 KiB partition image.
- `DT_NEEDED` names `libcmnlib.so`; this generic SONAME does not establish an
  ELF32 common-library image. The application itself is ELF64.

Those facts support checking the ordinary eight-segment Qualcomm split-image
layout. The production `.10` kernel image-assembly fixture has now passed against
this exact image: a private 7,208-byte MDT made from the first two file extents,
plus all eight program-header segments, produces the exact expected 208,631-byte
contiguous buffer. The same run passed the fixture's ELF32/ELF64 bounds,
truncation, invalid-header and overflow cases. Structural metadata and the exact
command are in `validation/keymaster-image-assembly.json`. The derived MDT stays
in the existing private firmware directory with mode `0600`; no firmware bytes
were added to this repository.

This confirms compatibility with the production assembly helper, but does not
prove the current bootloader's residency or the exact
application registration name, authorize new device reads, or establish the
live behavior of the now-recovered Keymaster initialization handshake. Any eventual extraction must validate
the selected signed image, offsets, lengths and firmware identity against the
authorized source and retain its provenance privately.

Service dependencies will need to establish the required listener supplicant,
correct common library and verified Keymaster application availability before
the native auth broker becomes usable. The once-per-TA `SET_VERSION` operation
must match the verified stock provider exactly. A guessed or skipped handshake
must not be used to make an unverified backend appear functional.

## Stock negotiation recovered — 11 September

Private analysis of the separately authorized `libkeymasterdeviceutils.so`
resolved the exact GET_VERSION/SET_VERSION request words and shared-buffer
partitioning. The native codec work is in `../fpc-qsee/gatekeeper.md`; this broker
now calls it during backend preparation. The stock constructor sends both exchanges for each
client, but the secure app applies configuration once per loaded TA instance.
GET_VERSION does not report the stored client settings; later SET_VERSION
success cannot verify or repair them. Application lookup and an attach operation
can establish residency, not known initialization history or a working listener.

## Minimal transport integration design

The current transport can already express the stock secure-world layout. Its
userspace `fpc_qsee_exchange()` puts the response memref at
`round_up(request_len, 64)`, so that local mapping is not the stock buffer
partition. However, the reviewed `.10` backend independently copies the exact
request and response capacities into contiguous kernel-only memory:
`drivers/tee/qseecom/core.c:qseecom_tee_invoke_func()` calls
`qcom_scm_qseecom_app_send(app_id, b, req_size, b + req_size, rsp_size)`.
The SCM helper forwards those lengths and physical addresses unchanged. The
userspace alignment gap never reaches the TA.

| Exchange | Request length | Secure response offset | Response capacity |
| --- | ---: | ---: | ---: |
| GET_VERSION | 4 | 4 | `0x9ffc` |
| SET_VERSION | 24 | 24 | `0x9fe8` |
| Fresh enrollment, 64-byte service credential | 96 | 96 | `0x9fa0` |
| Verification, 58-byte handle and 64-byte credential | 154 | 154 | `0x9f66` |

Every row totals `0xa000`. No kernel alignment change or persistent shared-memory
allocation is required for this framing. The kernel already allocates a fresh
secure staging buffer per exchange, so persisting a userspace mapping would not
give a stable secure-world address across calls.

The implemented adapter for `struct sargo_gk.exchange` follows these rules:

1. Require an already-open `keymaster64` client session, request length at least
   four and less than `SARGO_GK_BUFFER_SIZE`, and response capacity exactly
   `SARGO_GK_BUFFER_SIZE - request_len`, checking bounds before subtraction.
2. Forward those exact lengths to `fpc_qsee_exchange()` with no auxiliary
   buffer and no pointer fixup. Retain the existing request/response status
   separation and sensitive-memory cleanup. Do not pad the codec's request
   length to four or 64 bytes.
3. Keep application attachment, listener readiness and configuration lifecycle
   outside that exchange callback. A token request must not load an absent TA,
   select alternate firmware, or enroll a credential.

`test-auth-backend.c` now exercises these exact length/capacity pairs and an
odd-length password through the production userspace transport. It checks
adjacent caller request/response buffers, strict memref lengths, status failures,
pre-exchange cancellation and full shared-memory erasure. The production kernel
invoke fixture also asserts that the SCM response pointer immediately follows
the unpadded request. User-local response alignment remains unchanged.

The new codec's response sentinel detects an exchange callback that leaves its
output untouched. It cannot prove the real TA wrote a status word: this
transport zero-fills kernel response staging and copies its full capacity back.
GET_VERSION's exact version check rejects an all-zero reply. A zero SET_VERSION
status remains the stock protocol's acknowledgment, not evidence of new
configuration or a written-byte count.

## Residency and readiness checks before activation

A controlled trial can first establish the correct public TEE implementation
with `TEE_IOC_VERSION`, then attach specifically to `keymaster64`. The normal
client open path checks the driver's loaded-app registry and otherwise performs
the QSEE application-manager `APP_LOOKUP`; it sends no Keymaster command and
does not load firmware. Keep `ENOENT` for an absent app distinct from a missing
TEE node, permission failure, or malformed SCM response. Do not use the ordinary
`qsee-app-loader` as a read-only probe: its acquisition helper loads firmware
after an `ENOENT` attachment result.

Attachment proves a currently registered name, not the loaded image's hash or
its initialization history. Boot-loaded applications have generation zero and
this driver never unloads them on close. Driver-loaded applications are
reference-counted, so closing the last session can unload them; retain an
established loader/session anchor and do not force unload/reload to manufacture
a fresh SET_VERSION state. The current userspace session does not expose which
provenance branch resolved the app. An automatic fallback to `keymaster` is
also inappropriate here: the FPC wrapped-key path specifically expects
`keymaster64` identity.

Once separately authorized, GET_VERSION alone is the recovered observational
Keymaster command: require status zero and `[4, 0, 4, 165]`. Do not call the
combined negotiation helper merely to inspect readiness, because it also sends
SET_VERSION. Neither successful attachment nor GET_VERSION proves that secure
storage callbacks work. No available query reads back the once-per-loaded-TA
client configuration; that history remains a separate activation condition.

The native supplicant registers FS listener 10 and GPFS listener `0x7000`, then
emits `READY=1`. This establishes those registrations at that moment, rather
than implementing Android's `vendor.sys.listeners.registered` property. The reviewed original daemon had a health gap: it retried after losing listeners
inside the same process while systemd could retain stale readiness. The new
`1.3` package exits on post-readiness transport loss, allowing the supervisor to
withdraw readiness and restart the unit. It also checks the secure registration
status before announcing readiness. COPR10973847 passed, and downloaded RPM
signatures are verified. The broker and provisioning units use BindsTo/After for
that lifetime rather than running an independent `systemctl is-active` probe.

The two implemented listener services also do not prove that every Keymaster
storage operation is supported. Keep a controlled trace of listener IDs,
operation status and errors without credential, handle or token bytes.

## Remaining kernel transport conditions

The controlled trial must still account for these transport conditions:

- The `.10` invoke staging buffer is freed without an explicit wipe.
  `qcom_tzmem_free()` and pool destruction do not zero its contents. Userspace
  cleanup does not erase this kernel copy of the credential or HAT. Prepare a
  separately reviewed kernel change to wipe the entire staging allocation on
  every exit before freeing it. This fix is committed in `.11`, passes the
  production-function ARM64 fixture, and passed COPR10973843 with verified RPM signatures. Real
  credentials must use that corrected kernel, not the earlier `.10` image.
- Synchronous invocation has no implemented cancellation operation. A listener
  wait is deliberately uninterruptible for up to ten seconds per callback, and
  the SCM sequence can service multiple callbacks. The broker's five-second
  socket-I/O deadline therefore cannot bound a secure command. Preserve single
  transaction ownership and sensitive-buffer lifetime until the command
  actually completes; do not close a session underneath an in-flight call or
  retry an ambiguous enrollment. `BLOCKED_ON_LISTENER` remains unsupported and
  returns `EBUSY`; an automatic retry is not a recovery design.

These remain offline results. Image
`671197f9f3bf539fc4e1fd138843a8739df3958cabcacd0e5f9ca6a3baaa9996` now includes
this backend, the corrected kernel/listener and reviewed policy outputs. Its
package/boot/PAM/policy comparison and installed unit-graph checks pass, with the
broker socket and provisioning template masked. No image was staged and no real
firmware or authentication operation has been exercised. The packaged `README.md`
is the immutable 0.2 release snapshot from before this image assembly; current
image evidence is under `devices/google-sargo/fingerprint-trial/image/validation/v3-*`.
