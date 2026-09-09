# lpac for PocketFed

This package provides the local profile assistant CLI, not a background daemon
or graphical eSIM manager. It neither starts a modem service nor enables,
downloads, deletes, or switches a SIM profile at installation time.

## Source and packaging

The source is upstream lpac v2.3.0, resolved to commit
`c2fcf5e4b21c712d54e35a11da2ad9ad134fb821`. `Source0` uses that exact commit;
`SHA256SUMS` records the archive checksum. The patches are maintained as one
reviewable patch against that baseline, including hardware-independent tests.

Build dependencies are CMake, a C compiler, Ninja, system cJSON, libcurl,
PC/SC-lite, libqmi (at least 1.35.5), libqrtr-glib, and libmbim. Python and OpenSSL
are used by regression tests. Upstream's small cJSON extension is retained, but
the bundled parser and parser header are removed during RPM preparation.

The CLI and its private production TLS root are installed. The internal lpac libraries are linked into the CLI;
there are no private shared-library paths, exported development headers, or
separately installed static archives. cJSON and the backend dependencies are
system shared libraries. The package uses the LGPL-2.1-only option for libeuicc;
it does not rely on upstream's alternative commercial license.

Runtime certificate verification retains libcurl's normal system CA file and
adds a hashed, application-private CA directory at `/usr/share/lpac/certs`.
This directory replaces libcurl's default CAPATH, not its CAINFO bundle; the
Fedora/OpenSSL package is tested with this arrangement. Source builds default
to an empty `LPAC_HTTP_DEFAULT_CAPATH` and retain libcurl's original defaults.
No certificate is added to Fedora's global trust store, and ordinary system
CA bundle updates continue to apply. The package requires `ca-certificates`.
PC/SC users need the `pcsc-lite` daemon, which is a
weak dependency; direct Qualcomm QRTR access does not require that daemon.
An explicit, nonempty `LPAC_HTTP_CAINFO` selects a CA file and suppresses the
packaged additional directory. `LPAC_HTTP_CAPATH` can explicitly select a hashed
directory, including alongside a custom CAINFO file. Empty/unset overrides use
the packaged default behavior. A missing/invalid CA file or unsupported curl
CA-directory option fails closed; missing additional roots cannot authenticate
their servers. Peer-chain and hostname checks remain enabled, with no insecure
environment-variable fallback.

### Production GSMA root provenance

Some production SM-DP+ servers use GSMA's dedicated PKI rather than public web
CAs. The included `gsma-ci.pem` is the production **GSM Association - RSP2 Root
CI1**, not a test CI or a certificate opportunistically trusted from a server.
It is copied verbatim from ChromeOS Hermes at the pinned platform2 commit
`79723e8bbafdd2d3ef711af89692d3cac87b26f6`, path `hermes/certs/prod/gsma-ci.pem`:
https://chromium.googlesource.com/chromiumos/platform2/+/79723e8bbafdd2d3ef711af89692d3cac87b26f6/hermes/certs/prod/gsma-ci.pem
The source repository's BSD-3-Clause license is retained as LICENSE.chromiumos.

Certificate DER SHA-256:
`5E3E91FD454327C3AF5D32A7A73BBC59FE43AA7D85FD32D5DB44423F80A56BB3`.
PEM file SHA-256:
`01374ed6bc89ffa446d9dd38d52a8280624c5add811ba9dee7bea0bdc14b26e9`.
The package verifies the fingerprint, self-signature and hash-directory link.
It does not bundle test roots or claim to cover every production eSIM PKI.

This implements authenticated HTTPS, not a claim of full GSMA certification or
automatic revocation enforcement. The successful handset provisioning trial
also checked the issuer's current signed CRL before use; this client does not
currently fetch or continuously enforce CRLs/OCSP. Keep that limitation visible.

## Backend selection and cellular-service safety

Select `LPAC_APDU=qmi_qrtr` explicitly for a built-in Qualcomm QRTR modem.
The separate `qmi` backend is for QMI device nodes and has different slot
selection behavior. Do not substitute one backend for the other simply because
both use libqmi.

On the tested Sargo firmware, APDU slot numbers are **logical**. The embedded
eUICC is physical slot 2, but it must be mapped to logical slot 1 before normal
UIM logical-channel requests can access it. Do not use a physical slot number
as an APDU slot number or assume that an inactive embedded card is inaccessible
hardware. Changing the physical-to-logical mapping interrupts the existing SIM
service and must be deliberate, with a recorded restoration path.

In this QRTR backend, `LPAC_APDU_QMI_UIM_SLOT` selects the logical APDU slot
(default 1). Leaving `LPAC_APDU_QMI_PHYSICAL_SLOT` unset does not request any
mapping change. Setting it explicitly, for example to `2` on the verified
Sargo, opts into a temporary mapping transaction: save the complete existing
mapping, map that physical slot to the requested logical slot, perform the
operation, and attempt to restore the saved mapping at teardown. Restoration
also applies after profile-management operations; persistent modem SIM routing
is a separate system policy decision.

The existing libeuicc teardown API returns `void`. A restoration error is
reported on stderr but cannot currently turn an otherwise successful operation
into a failing CLI exit status. Therefore independently verify the complete
post-operation mapping and cellular-service recovery; a zero exit status or a
printed success object alone is not proof that restoration succeeded. Abrupt
termination, power loss, or modem loss also require independent recovery.

Plain `chip info` and `profile list` commands are inventory operations, but
backend initialization and slot handling must still be accounted for. Preserve
the current mapping, avoid concurrent card-management tools, and do not log full
EIDs, ICCIDs, activation codes, or downloaded profile contents in public output.
Downloading, enabling, disabling, deleting, and sending notifications are
separate operations, not part of inventory validation.

The lpa-gtk GUI is not supplied by this package. Its current startup sequence
can process and remove pending eSIM notifications, so launching it is not a
strictly read-only probe.

## Verification

The RPM runs the bundled CTest regressions and verifies the compiled backend
list, reproducible package version, dynamic system-cJSON dependency, and absence
of an installed RPATH. Tests do not need a phone, SIM, carrier account, modem
service, or internet connection. They do not establish live profile-management
or cellular-service acceptance; those remain separate device checks.
