# IMS bearer lifecycle recovery

This downstream patch addresses the resume sequence observed on google-sargo:
ModemManager restarts while 81voltd is still running, firmware requests an IMS
connection before the new modem is registered, and the early bearer Connect is
cancelled. 81voltd 1.2.0 neither retries that connection nor reports its failure
to firmware. Firmware can also stop the pending request before bearer creation
completes.

Start Connection now promptly acknowledges its allocated local handle. Actual
CreateBearer and Connect wait for ModemManager REGISTERED, CONNECTING or CONNECTED;
DISCONNECTING is excluded. The eventual ConnectionChanged indication reports the
connected address or the existing protocol's down result (error status 0, code 13).
An LTE data connection is not treated as proof of IMS voice registration.

The daemon serializes Connect/Disconnect and tries transient Connect failures at
most 3 times (1 and 2 second backoffs). Each new request has a 60 second readiness/address
deadline; creation has a separate 60 second deadline. Permanent failures and exhausted
budgets produce one terminal down indication. Stop removes the request before any
late asynchronous completion can publish an address or restart it.

Stop checks subscription as well as the local handle, and accepts the original
connection ID for firmware that stopped before observing the Start ACK. Ambiguous
local/original ID matches are rejected without disconnecting either session. Same-request
retransmissions retain their handle and bearer; a conflicting live request cannot
overwrite those identifiers. Free local handles are allocated in rotation rather
than immediately reusing a retired handle. IMSD's 8 bit local handle has no generation
field: a packet delayed across a complete handle wrap is not distinguishable on the
wire. The patch does not invent protocol fields.

CreateBearer calls retain their completion after cancellation, since cancelling a
local D-Bus call does not necessarily cancel the remote operation. A late bearer is
deleted only on the same modem generation and D-Bus owner. A modem replacement
invalidates old connections and handlers; stale callbacks never act on a reused
object path owned by the replacement ModemManager process.

The private-D-Bus regressions compile the production sources and run a fake
ModemManager; they require no phone, system bus, network or real QRTR modem. Test
builds shorten retry/deadline delays. Production builds retain the defaults above.
Run `meson setup build`, `meson compile -C build`, and
`meson test -C build --print-errorlogs`.

Source audit: upstream v1.2.0 is 7c0cd9442d71b55260c9917c89ebc4bd20e283a8.
Upstream main a7794dd6c8ac216a97dc5a931edab2dfc46eca2a was inspected on 2026-09-07;
its two later changes concern QRTR decode errors and debug documentation, not this
lifecycle problem. The patch keeps the upstream 1.2.0 protocol definitions.

## PocketFed build

This directory maintains the existing PocketFed packaging, with release
`1.1.pocketfed` and the recovery patch applied to the checksum-pinned 1.2.0
archive. The source RPM contains the same spec and patch bytes as this directory.
The RPM's `%check` runs all 18 private-bus/wire tests.

[COPR build 10955562](https://copr.fedorainfracloud.org/coprs/build/10955562)
succeeded for Fedora Rawhide aarch64, Rawhide x86_64 and Fedora 45 aarch64.
Each target passed all 18 tests. Runtime RPM signatures were checked against
the samcday/pocketfed key. [build.json](build.json) records source and RPM hashes,
patch hash and validation results. Source preparation and the package regression
command are described in the [package documentation](../README.md).

The Sargo image and verifier require this PocketFed release. Device acceptance
uses the [coordinated suspend/wake/call checklist](../../devices/google-sargo/diagnostics/README.md).
