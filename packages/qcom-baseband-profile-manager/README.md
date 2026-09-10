# Qualcomm baseband profile manager

Experimental OpenIMSd tooling for [PocketFed #46](https://github.com/samcday/pocketfed/issues/46).
Upstream is pinned to `e5cc292dc95d3745341db67387d5fd0ff0e8c9e7` (2026-04-29).

This is a **resident-profile selector**, not a vendor-catalogue importer. It
reads the primary provisioning SIM, matches its carrier against configured PDC
IDs, and selects/activates a profile already loaded into the modem. It does not
download eSIMs, establish IMS bearers, or manage Android vendor partitions.

## Image defaults

The base image includes the package, but explicitly presets the service off.
The RPM installs no `/etc/qcom-baseband-profile-manager.toml`; a systemd condition
also prevents startup without that explicit configuration. The example has no
carrier IDs or fallback policy. No proprietary MBN is included in any RPM.

The three Qualcomm device layers allow the `libqmi*` package family from COPR:
they install `libqmi-utils`, whose exact-version library dependency must match
the patched libqmi supplied by the base image. `base/test-qcom-profile-manager`
checks this relationship and the deliberately inactive default policy.

Do not enable this alongside another active PDC policy owner. Before automatic
enablement, we still need device-local catalogue discovery/import, firmware
provenance checks, coordination with the existing boot helper/ModemManager,
verified protocol error handling and modem-loss recovery. Cold boot, SIM changes,
IMS, calls, SMS and data still need end-to-end coverage of that combined system.

## Fixes and dependencies

The daemon patch fixes two reproduced defects:

- The carrier index overwrote earlier entries sharing an MCC, so configuring
  Telstra and Optus together lost the first carrier.
- SIM callbacks/polling passed an already-scheduled asyncio task to `call_soon`;
  card changes also scheduled the callback twice.

Four focused regression tests fail against the unpatched source and pass after
the patch. The modem-specific Python workaround tried during diagnosis was
discarded: the real fix belongs in libqmi.

`../libqmi` backports upstream `082bf3454c011e1481375e843a0c91c9e338d422`, which
adds missing nested GArray element annotations. Without it, current PyGObject
raises `TypeError` when reading UIM application IDs and PDC profile IDs. This
is an existing upstream fix, not a new PocketFed protocol implementation.

Separate RPMs provide `python3-pyosmocom`, `python3-gsm0338` and
`python3-statemachine`; dependencies are not vendored into the manager package.
The state-machine package has one test-only adjustment for pytest 9's removed
legacy collection-hook argument. Each source archive has a recorded SHA256.

## On-device trial, 2026-09-10

Tested on **sam-sargo**, not test-sargo. No phone reboot, installed-package
transaction, `/usr` overlay, keyboard change, or persistent service enablement
was used. Python modules, an extracted matching PyGObject RPM, and a rebuilt
ARM Qmi typelib were confined to a private `/tmp` directory. The typelib was
selected only for the trial process via `GI_TYPELIB_PATH`; this trial did not
replace installed libqmi or other modem clients.

Starting state was independently observed: empty physical tray mapped to the
primary logical slot, eSIM unmapped, no PDC software profiles, ModemManager
failed with `sim-missing`. Mapping the existing eSIM and provisioning its USIM
allowed the upstream client to derive Optus PLMN `505/02`. No eSIM profile was
downloaded, enabled or deleted.

The trial read the following file directly from retained `vendor_a` using
read-only debugfs; blob-wrangler was not involved in this import:

```
/rfs/msm/mpss/readonly/vendor/mbn/mcfg_sw/generic/AUNZ/Optus/Commercial/AU/mcfg_sw.mbn
```

Vendor build: Android 12 `SP2A.220505.006/8561491`.
Modem revision: `MPSS.AT.4.0.2.c4.1-00145-SDM670_GEN_PACK-1.466700.3`.
File size: 119304 bytes.
SHA256: `3bf5320896b577dfa86aee77939a3c97308aa5208e4940c4775e6f53809e2b2d`.
PDC ID: `23ef3405d5f81c88602dabe572bcfcdf787ba36f`.
PDC description/version: `Optus_Australia_Commercial`, `0x08014411`.

Upload was performed separately with the existing fixed qmicli helper; **the
new daemon did not discover or upload the file**. A bounded wrapper then ran
the daemon's real state machine, allowing only that exact profile to be
selected/activated. It reached `wait_events`; a separate PDC read confirmed the
expected active ID with no pending profile. A second run forbade all PDC writes
and reached the same state with **zero mutations**. The unwrapped CLI also
recognized the existing correct profile and released its clients on SIGTERM.
ModemManager subsequently reported connected/home on `50502`; this is not a
fresh end-to-end voice, SMS or cellular-data test.

Local package checks: codec 21 passed; pyosmocom 43 passed; state machine
379 passed and 3 upstream expected failures; manager 4 passed. The ARM libqmi
source build passed all 5 Meson test targets, plus the generated-GIR regression
for PDC and both UIM byte arrays.

## Publication and packaged-payload verification

All five final packages built successfully for Rawhide aarch64 and x86-64 in
`samcday/pocketfed`; exact build IDs and NVRs are in [build.json](build.json).
Downloaded RPM signatures were verified against the project's public key, and
the signed source RPMs' archives, specs, patches and extra sources matched the
recorded source digests and this packaging tree.

The final signed COPR Python packages and libqmi typelib were extracted under
`/tmp` on sam-sargo, not installed. They passed the same real-modem idempotence
test with PDC mutations forbidden. A fresh Fedora ARM container also installed
the signed packages through the base repository, then installed matching
`libqmi-utils` through the Sargo allowlist. CLI help, unit verification, absent
carrier configuration and disabled service preset all passed. A full OSTree
image build is separate from this package/install test.

An initial test using an already-populated development container encountered
DNF's vendor-change restriction; that is not a fresh-image result. Existing
Fedora installations may need an explicit, scoped vendor-switch transaction
when adopting the patched libqmi. No such transaction was run on the phone.

Remaining rpmlint findings are explicit GI runtime dependencies (required because
RPM cannot infer them from Python imports), upstream's historical FSF address
in its unchanged GPL text, and one cosmetic description-line-length warning.
No claim of completed Fedora package review is made.

At the final observation the eSIM mapping and Optus profile remained working,
and no trial daemon was left running. Concurrent work had created a new staged
deployment and development overlay during the trial; neither was created nor
modified by this work. There was no attempt to roll back that unrelated state.
