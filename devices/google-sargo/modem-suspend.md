# Sargo suspend crash and outgoing-call failure

Investigation on 7 September 2026, 08:42–08:58 AEST, following the capture at
`/tmp/sargo-call-triage-20260907-0839/handoff.md` and the same suspend
assertions recorded on 6 September during earlier device validation.

The suspend assertion is confirmed from the actual ModemManager core.
Post-recovery LTE data was working while IMS was unregistered and IMS voice
and SMS were unavailable. Reconnecting the IMS bearer alone did not restore
registration. A modem low-power/online transition restored IMS registration
and service availability, without restarting services. Sam subsequently
confirmed a successful outgoing call with audio flowing both ways; the
09:11 call log confirms ringing-out and active states.

## Captured versions

| Component | Observed value |
| --- | --- |
| Booted image | `ghcr.io/samcday/sam-sargo:rawhide` |
| Image digest | `sha256:3a9430a43d718f2a5d7fd993941790e47ba987e2d292ebf078684d40bdf6cf04` |
| Kernel | `7.1.2-0.pocketfed.sdm670.6.fc46.aarch64` |
| ModemManager / ModemManager-glib | `1.24.2-4.1.pocketfed.fc45.aarch64` |
| 81voltd | `1.2.0-1.fc46.aarch64` |
| libqmi / libqmi-utils | `1.36.0-4.fc45.aarch64` |
| libqrtr-glib | `1.2.2-10.fc45.aarch64` |
| NetworkManager | `1.58.1-1.fc46.aarch64` |
| Calls | `50.0-3.fc45.aarch64` |
| callaudiod | `0.1.99-4.fc45.aarch64` |
| rmtfs / tqftpserv | `1.3-1.fc46.aarch64` / `1.2-1.fc46.aarch64` |
| Modem firmware | `MPSS.AT.4.0.2.c4.1-00145-SDM670_GEN_PACK-1.466700.3`, built 3 January 2022 |

The booted deployment also has the GTK `4.23.4-1.1.pocketfed.fc46` override
and Tailscale layer. These were not changed.

## Suspend crash: proved bearer-limit accounting bug

At 08:28:32, `mm_base_manager_cleanup()` calls
`mm_iface_modem_count_bearers(ACTIVE)` before starting per-modem cleanup.
The core for PID 11464, interpreted with matching debuginfo, contains:

```text
flags = MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE
ctx.count = 1
bearer-list max_active_bearers = 0
bearer-list max_active_multiplexed_bearers = 254
```

The installed executable compares all active bearers, including multiplexed
ones, against the nonmultiplexed limit: `0 >= 1` fails. This is not excessive
bearer allocation or evidence of a full modem. Even one active multiplexed
data bearer is sufficient on this device.

Upstream [commit 0edcb916ad2b](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mobile-broadband/ModemManager/+/0edcb916ad2b7267caf73bbd9a31e46da0727a00)
fixes this exact accounting error by including multiplexed capacity for
ACTIVE/CONNECTED counting. The patch applies cleanly to the exact installed
source RPM after its existing netlink use-after-free patch. The corrected
limit for this captured state is 254.

The matching [COPR source RPM](https://packages.redhat.com/api/pulp-content/public-copr/samcday/pocketfed/fedora-45-aarch64/Packages/m/ModemManager-1.24.2-4.1.pocketfed.fc45.src.rpm)
contains the separate `c0900eefe196` netlink fix but lacks this bearer fix.
Its executable matches the captured phone executable, SHA-256
`5a5236f1fed4098f5f2e881c626d5f53d8c7a3c3ce776954eddcb515344c428f`,
build ID `e5b0d9f01dbdf94a3ec7240d8d2c66945a3eb8c0`.

The current boot had seven automatic ModemManager restarts by capture.
September 6's recorded suspend assertions and the September 7 event follow
the same failure pattern; only the September 7 08:28 core was analysed here.

## Voice/IMS failure, separate from data and audio routing

After resume, 81voltd deferred an IMS connection at 08:35:01.353 because
ModemManager had not rediscovered the modem. At 08:35:01.570 it also logged
`IMSD Stop Connection: unknown connection ID 101`.

The IMS bearer connection failed with `operation cancelled` at
08:35:31.711, while the modem was still enabling. The modem became enabled
at 08:35:31.740, home-registered at 08:35:31.745, and data-connected at
08:35:32.357. The outgoing call then dialled from 08:35:40 to 08:36:07 and
terminated with an unknown reason, without an active state.

Before intervention, bearer 0 used APN `ims`, IPv6 and profile 2. It was
disconnected, with one failed attempt and no subsequent retry. Bearer 2,
the `mdata.net.au` internet connection, was connected and multiplexed on
`qmapmux0.0`. The initial EPS attach bearer used `telstra.wap`.

NAS reported LTE available, voice support and IMS voice support. The MM
Voice interface reported `EmergencyOnly=false`. None establishes successful
IMS registration. A successful IMSA query at 08:50:09 explicitly returned:

```text
IMS registration: not-registered (0), technology WWAN (1)
IMS voice service: unavailable (0)
IMS SMS service: unavailable (0)
```

The handoff had already excluded the known WirePlumber cross-role-link
failure and confirmed the installed routing correction. No audio services
or configuration were changed during this investigation.

## 81voltd lifecycle findings and remaining uncertainty

The exact [81voltd v1.2.0 source](https://gitlab.postmarketos.org/modem/81voltd/-/tree/v1.2.0)
was verified against the repository's archive checksum. It handles modem
object removal by clearing its tracked bearer map; an unchanged PID alone
does not prove stale state.

However, `qvd-modem.c` processes deferred CreateBearer requests immediately
on modem object addition, without waiting for enabled/registered state.
`qvd-server.c` replies successfully to IMSD Start after bearer creation and
starts Connect asynchronously. A later Connect error is logged/emitted,
but the server does not subscribe to the connect-error signal, notify the
firmware of that failure, or schedule a retry.

This source behaviour and the recorded one-attempt cancellation support an
early connection race during modem enabling. The precise ModemManager
force-cancel caller was not captured at debug level and remains unproved.
Registration notifications while both cached domains are unregistered are
one source-supported route. The unknown Stop during a deferred Start may
also leave a late success associated with a request the firmware abandoned;
the normal logs do not establish the exact request pairing.

Restarting 81voltd alone is unsuitable as a general recovery: it starts with
an empty bearer map, does not adopt existing bearers and does not release or
disconnect them on exit. A later request can create another bearer. Its
[README](https://gitlab.postmarketos.org/modem/81voltd/-/blob/v1.2.0/README.md)
documents the missing error propagation and modem low-power/online recovery.

## Targeted recovery and verified result

All baseline logs, bearer states, versions and the exact 08:28 crash core
plus executable were preserved before recovery. Each recovery checked that
there were no calls. Wi-Fi was the default management route before the
modem power transition.

| Time AEST | Action or observation |
| --- | --- |
| 08:50:47–48 | Connected only existing IMS bearer 0 with `mmcli -b 0 --connect`. IPv6 connection succeeded on `qmapmux0.1`. |
| 08:51:05 and 08:51:57 | IMS remained not registered, voice/SMS unavailable despite the connected IMS bearer. |
| 08:54:02 | `mmcli -m 0 --set-power-state-low` succeeded; both cellular bearers disconnected. |
| 08:54:04 | NetworkManager automatically re-enabled the modem, bringing power back on. |
| 08:54:05 | Explicit power-on returned WrongState because automatic enabling had already advanced; explicit enable succeeded. This was not a controlled three-second low-power dwell. |
| 08:54:07–08 | Internet and existing IMS bearer reconnected. |
| 08:54:45 | IMSA reported registered (2) over WWAN, voice and SMS available (2) over WWAN. |
| 08:57:59–08:58:02 | IMS registration and voice/SMS availability remained restored; daemon PIDs/restart counts unchanged, no calls present. |
| 09:11:01–09:11:19 | Sam's outgoing call dialled at 09:11:01, rang out at 09:11:03, became active at 09:11:08 and ended at 09:11:19. Sam confirmed audio flowing both ways. |
| 09:12:10 | No calls remained; both daemon PIDs and restart counts were still unchanged. |

ModemManager remained PID 11888, restart count 7; 81voltd remained PID 1502,
restart count 0. During the investigation and targeted recovery, no service restart, reboot,
suspend test, package installation or APN/profile edit was performed. The low-power transition briefly
interrupted cellular data. The subsequent user-operated call validates call
setup and two-way audio; delivery of an SMS was not tested.

## Maintained package corrections

The Fedora ModemManager dist-git packaging is now maintained in
[packages/ModemManager](../../packages/ModemManager/README.md), based on Fedora
commit `fc074fd1e3d35afc57da502beb7790c361bd73ef` (1.24.2-5).
PocketFed release `5.1.pocketfed` retains the existing netlink patch and adds
upstream `0edcb916ad2b`. All three Qualcomm device image definitions and their
verifiers require the new release.

[COPR build 10955548](https://copr.fedorainfracloud.org/coprs/build/10955548)
succeeded for Fedora Rawhide aarch64, Rawhide x86_64 and Fedora 45 aarch64.
Each target passed nine production-source bearer counter cases and all 32
upstream Meson tests. Runtime RPM signatures were verified against the
samcday/pocketfed signing key; source/RPM hashes and results are recorded in
[historical build record](../../packages/ModemManager/builds/1.24.2-5.1.pocketfed.json).

[81voltd's maintained package](../../packages/81voltd/README.md) now carries
readiness gating, prompt Start acknowledgement, pending-request cancellation,
bounded Connect retries and terminal error indications. It preserves callback
ownership across ModemManager replacement and serializes Connect/Disconnect.
The Sargo image requires release `1.1.pocketfed`. Its private-D-Bus and IMSD
wire regressions exercise production source without accessing a modem.
[COPR build 10955562](https://copr.fedorainfracloud.org/coprs/build/10955562)
succeeded on the same three targets, each passing all 18 tests (14 lifecycle
and four wire scenarios). All three runtime RPM signatures were verified;
[its build record](../../packages/81voltd/build.json) contains artifact hashes
and validation limits.
The [package CI helper](../../packages/README.md#modem-package-regression-tests)
verifies both source archives, applies the declared patches without fuzz and
runs the maintained regressions.

Sam's successful recovered call established two-way audio before these changes.
At 09:38 AEST IMS remained registered with voice and SMS available, and both
daemon PIDs/restart counts remained unchanged. Physical suspend/wake/call
acceptance of the new packages is still pending; neither a successful build nor
an LTE data connection establishes that result. Use the
[controlled acceptance checklist](diagnostics/README.md) and capture each
failure before attempting recovery.

## Staged rollout, 09:58 AEST

Both fixes are staged together on sam-sargo in deployment
`356d00c9ee8564b36159ed521ff4a44d0427ec711408ea8f4a4cf97b2c2c57a9`:

- ModemManager and ModemManager-glib `1.24.2-5.1.pocketfed.fc46.aarch64`.
- 81voltd `1.2.0-1.1.pocketfed.fc46.aarch64`.

The phone verified all three RPM signatures and hashes. A cache-only transaction
preview and the final deployment both preserved the GTK override, pending
feedbackd-device-themes layer and Tailscale. The original booted deployment
`1912fa2d44e96afbdaf7e765e4a611b21bf528d16e97cbbb892a31bde7885c37`
is retained for rollback. The same signed runtime RPMs also passed a combined
upgrade and the updated Sargo image verifier in an isolated aarch64 Sargo
container with networking disabled.

During staging, no reboot or live application was performed. At that point the
running versions were the captured originals: ModemManager PID 11888 with seven
restarts and 81voltd PID 1502 with zero restarts. At 09:58 IMSA still reported
registered with voice/SMS available over WWAN, with no calls. This preserved the
working baseline before activation. The subsequent user-operated reboot and
verification of the corrected packages are recorded below.

Build logs, signed artifacts, source hashes, transaction preview, pre/post
states and a SHA-256 manifest are retained in
`/tmp/pocketfed-modem-hardening-20260907/`. This directory is private and separate
from the original crash/recovery captures.

## Activated reboot and cold-boot baseline

Sam rebooted the staged deployment and connected the phone to the host's FTDI
UART cradle. Boot ID changed to `4b818fb7-f39d-400c-b141-21e704e72f6d`, and the
booted deployment is the staged `356d00c9…` above. The four base overrides,
feedbackd-device-themes and Tailscale are present. The kernel remains
`7.1.2-0.pocketfed.sdm670.6.fc46.aarch64`.

| Observation | Post-reboot result, 7 September AEST |
| --- | --- |
| ModemManager / glib | `1.24.2-5.1.pocketfed.fc46.aarch64`; daemon PID 1469, active, zero restarts. |
| 81voltd | `1.2.0-1.1.pocketfed.fc46.aarch64`; PID 1534, active, zero restarts. |
| Daemon startup | ModemManager started 10:03:05.861; 81voltd started 10:03:06.256. |
| Registration/data | Home-registered at 10:03:37.339; internet bearer 1 connected at 10:03:38.558. |
| Internet bearer | APN `mdata.net.au`, IPv4, connected on `qmapmux0.0`. |
| IMS bearer | Bearer 2, APN `ims`, IPv6, profile 2, connected on `qmapmux0.1`; IPv6 settings obtained at 10:03:40.073. |
| IMSA at 10:05:47 | Registered, voice and SMS available, all over WWAN. No calls present. |

The boot journal has no ModemManager assertion, cancelled IMS attempt or
terminal `IMSD connection failed` message. Bearer 2's IPv4
`pdn-ipv4-call-disallowed` response was followed immediately by successful IPv6
settings; it was a packet-session family rejection, not an outgoing voice-call
failure. The DSI PLL/clock disable/unprepare warnings also present in this boot
match the earlier kernel capture before these RPM changes, including stack
offsets. They remain separate display bring-up evidence.

Receive-only UART capture used the observed FTDI adapter at `/dev/ttyUSB0`,
with its existing 115200 8N1 raw settings. The exact adapter identifier is
retained only in the private capture notes. It began at
10:03:42 and ran for three minutes, capturing the tail of startup; the early
boot was recovered from the full kernel/systemd journals over root SSH.
The reader transmitted no bytes and released the port on completion.
Initial kernel wall-clock dates precede clock correction; use boot IDs and
monotonic timestamps when comparing total boot duration.

This establishes a successful cold-boot modem/IMS baseline on the corrected
packages. No further reboot, recovery, suspend or call was initiated by the
investigator. Controlled suspend/wake and user-operated two-way-audio call
acceptance remain outstanding. A separate authorized Wi-Fi image rollout is
being coordinated; retain these modem overrides and record a new baseline if
that rollout changes the booted deployment.

## Private evidence and IMS query method

Evidence is stored locally under
`/tmp/sargo-call-investigation-20260907-0844/`, with a SHA-256 manifest.
It includes original baseline JSON, boot journals, versions, core archive,
typed core counters, source patch/applicability results, exact recovery
commands and raw IMSA responses. Raw captures contain phone/SIM identifiers,
addresses, IMS identities and process memory; keep them out of public reports.

The installed qmicli's unbound IMSA Get requests returned InvalidOperation.
A single fresh QRTR socket with client-local IMSA Bind and subsequent Get
requests was required. Binding 1 was accepted but its Gets still failed;
binding 0 returned valid status. No general subscription-number mapping is
claimed. Separate qmicli processes cannot preserve the same QRTR client by
reusing a synthetic CID.

The preserved `ims-read-qrtr.py` sends only IMSA Bind `0x33`, Get Registration
`0x20` and Get Services `0x21`, then closes its socket. Message formats and
enums follow the upstream libqmi [IMSA schema](https://github.com/linux-mobile-broadband/libqmi/blob/main/data/qmi-service-imsa.json)
and [IMSA enums](https://github.com/linux-mobile-broadband/libqmi/blob/main/src/libqmi-glib/qmi-enums-imsa.h).
Service 33 was node 0, port 78 in this boot;
rediscover the endpoint with `qrtr-lookup` before reuse. The helper installs
nothing and changes only its own diagnostic client's binding.

A maintained copy of the diagnostic is now
[diagnostics/ims-state.py](diagnostics/ims-state.py). Its default output omits raw
packets; `--raw` enables private wire evidence. Binding must be supplied
explicitly. This copy passed its decoder self-test and a read-only query on the
phone at 09:38 AEST, reporting IMS registered and voice/SMS available over WWAN.
