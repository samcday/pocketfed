# PocketFed development trials

For kernel, device-driver, or associated userspace work (including camera,
fingerprint, audio, charging, and Type-C), read `tools/liveboot/README.md` first.
The default hardware trial path is local kboop/fastboop liveboot on a designated
test device. Build locally, reuse a cached PocketFed userspace fixture, and boot
a coherent kernel/DTB/modules candidate. Public CI, COPR, a published OCI,
OSTree deployment, and installation partition images are not prerequisites for
an ephemeral trial. Use the normal package/image pipeline for promotion and
installed-deployment acceptance after the experiment succeeds. Historical trial
notes that require COPR describe their installed/package workflow; they do not
prohibit this local development loop. Follow any explicit current user constraint.

## Scope of the retained integration work

The `tools/liveboot` harness and sibling kboop additions include a runaway scope
expansion from the September 2026 trial work. Keep this work for now, including
the optional whole-root RAM staging and diagnostics, but do not treat it as an
agreed long-term fastboop architecture or a mandate for further expansion.
The USB-root Sargo path passed; RAM-resident startup still fails and cannot
validate USB disruption. Do not resume its debugging or promote its workarounds
unless the current task asks for that. The proposed device-side block cache,
LRU eviction and learned prefetching remain design ideas, not implemented here.
Distinguish the tested kboop integration from standalone fastboop CLI support.

## Entry points

- `just liveboot-fixture`: export a locally cached device OCI (registry digest or
  full local image ID), with optional local userspace overlay. No image is pulled
  or container started by the exporter.
- `just liveboot-kernel`: incrementally build or package an existing local Kbuild
  output into a coherent, hash-recorded candidate bundle.
- `just liveboot-prepare`: assemble immutable boot artifacts using that fixture
  and optional candidate bundle. This does not access a device.
- `just liveboot-boot`: select the exact test-device serial and retain UART capture
  and USB hosting for a recorded run.
- `just liveboot-sysrq`: explicitly request HELP or reboot through the active
  runner's UART. Keep `sysrq_always_enabled=1` in trial command lines.

`just fastboot` produces installation partition images and is a different path.
Source and reusable instructions belong in tracked `tools/liveboot/` and the
normal sibling `../kboop` checkout. `out/liveboot/` contains generated fixtures,
per-run binaries, candidate artifacts and logs; never hide sole source checkouts
there. Preserve concurrent changes in this shared repository.

## Select the transport for the experiment

USB-backed EROFS is the default for quick kernel and userspace iterations. Tests
that reset/disconnect the USB controller, change USB role, or remove the cable
need a storage strategy validated through those interruptions. The retained
whole-root RAM experiment has not passed that gate. A UART console alone does
not make root storage independent. Do not report a USB-root run as acceptance
of USB-loss behavior.

Match device product and exact serial, inspect UART ownership, and use the
runner's locks; do not take over another task's device or console. Keep hosting
until the disposable USB-root session has ended. RAM boot does not authorize
flashing, erasing, slot changes, or daily-driver deployment. Record source commit,
dirty patch/config/toolchain, image identity, kernel/DTB/module hashes and exact
run result. A successful systemd handoff is only the baseline; each subsystem
still needs its own measured acceptance test.
