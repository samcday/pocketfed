# Flatpak 1.19.0 can lose a nested sandbox's startup notification

Ungoogled Chromium failed to open on a Fedora Rawhide aarch64 phone because
`flatpak-portal` abandoned startup tracking before the nested sandbox's PID file
appeared. The browser remained alive waiting for `SpawnStarted`. Rebuilding the
same Fedora source with the proposed retry patch restored the signal, completed
the headless test, and opened the normal browser window.

The regression is in Flatpak's `org.freedesktop.portal.Flatpak` service. The
headless reproduction and portal-only comparison do not implicate Phosh or
`xdg-desktop-portal`.

## Affected version and source boundary

The tested device ran Fedora Rawhide, `flatpak-1.19.0-3.fc46.aarch64`, Bubblewrap
`0.12.0-1.fc46`, and Ungoogled Chromium `152.0.7977.82-1` from Flathub. The
application commit was
`0f995432c043dd4ddffca6ccfd2a4535412404766116aaae5d88134f4eea8e2c`.

The introducing commit is
[`21f413f17f241240c5c5d67b0ac61c4bb7504075`, "flatpak-instance: Make constructing failable"](https://github.com/flatpak/flatpak/commit/21f413f17f241240c5c5d67b0ac61c4bb7504075),
merged on 27 July 2026 through [Flatpak PR #6722](https://github.com/flatpak/flatpak/pull/6722).
The first release containing it is
[1.19.0 prerelease, published 11 August 2026](https://github.com/flatpak/flatpak/releases/tag/1.19.0).
Upstream main at `e382cbeb80ce9fbaab587a613a9f35ba0612d8cd`, checked on
8 September 2026, retains the failure path. Stable 1.18.2 does not contain this
constructor change. This does not imply that all launches on 1.19.0 fail, or
that older versions are free of other startup bugs.

## Reproduction

With the affected Flatpak and application installed, run from a regular user
session. Use a new, unused profile path for each attempt:

```sh
timeout --signal=TERM --kill-after=5s 40s \
  flatpak run io.github.ungoogled_software.ungoogled_chromium \
  --headless --no-first-run --no-default-browser-check \
  --disable-background-networking \
  --user-data-dir=/tmp/ungoogled-startup-repro-1 \
  --enable-logging=stderr --v=1 --dump-dom about:blank
```

Expected: blank-page DOM and exit 0. On the affected device, the command timed
out with exit 124, after logging `Spawn() returned PID ...` and `Waiting for ...`.
The portal journal reported a missing instance `pid` file. That file and its
corresponding `bwrapinfo.json` were present when inspected afterward. This is a
timing-dependent integration reproduction; the focused test below supplies a
deterministic ordering.

## Why it hangs

1. [The runner sends the instance ID](https://github.com/flatpak/flatpak/blob/1.19.0/common/flatpak-run.c#L1711)
   before writing its `pid` file later in startup.
2. The new
   [instance constructor](https://github.com/flatpak/flatpak/blob/1.19.0/common/flatpak-instance.c#L394)
   requires that file to contain a positive PID.
3. If the portal receives the ID first, its
   [instance-ID callback](https://github.com/flatpak/flatpak/blob/1.19.0/portal/flatpak-portal.c#L440)
   logs the construction failure and returns. It never enters the existing
   child-metadata retry loop or emits `SpawnStarted`.
4. [Chromium's Flatpak sandbox patch](https://github.com/flathub/io.github.ungoogled_software.ungoogled_chromium/blob/49c49e37524e5a1f0e2ff00d5b7328e209966ffa/patches/chromium/flatpak-Add-initial-sandbox-support.patch)
   waits for the PID mapping delivered by that signal. Its nested zygote may be
   running while the browser remains blocked.

The notification ordering and Chromium wait predate this regression. The
constructor change serves a useful purpose: rejecting PID 0 prevents callers
from accidentally signaling an entire process group. The proposed fix preserves
that validation.

## Proposed fix and evidence

The [patch](flatpak-1.19.0-retry-instance-pid.patch) retains the instance ID and
constructs the instance inside the existing asynchronous retry callback. A
missing PID file (`G_FILE_ERROR_NOENT`) is retried using the established backoff.
Other errors still stop tracking. Each attempt checks whether the child has
already exited, avoiding a startup signal after exit.

The real-device comparison on 8 September 2026 used identical browser arguments,
distinct temporary profiles, and a 40-second timeout:

| Portal binary | Browser result | Captured startup protocol |
| --- | --- | --- |
| Installed Fedora binary | Timeout, exit 124 | `Spawn` reply; no `SpawnStarted` during capture |
| Rebuild of the exact Fedora SRPM, unchanged | Timeout, exit 124 | `Spawn` reply; no `SpawnStarted` during capture |
| Same build with the proposed patch | Blank-page DOM, exit 0 | `SpawnStarted(12098, 17)`, then successful `SpawnExited` |

The normal graphical launch also started GPU and renderer processes, and the
device owner confirmed the browser window was visible. No sandbox-disabling
flags were used. The trial selected the patched portal through a runtime user
service override; it did not install a package or persist across reboot.

The [build recipe](build-portals.sh), [source hashes](sources.sha256),
[build notes](build-notes.md), and [filtered validation evidence](validation/)
pin the Fedora SRPM and retain its existing `fd-conflation.patch` and
`eagain.patch`. Only the additional portal patch differed between the two
rebuilds. These were debugoptimized builds, not byte-identical Fedora RPM
rebuilds. The journal excerpts replace the device hostname with `test-device`;
startup PIDs, instance IDs, timestamps, and signal payloads are unchanged.
Full session logs, browser data, and unrelated device diagnostics are omitted.

The [production-source harness](test-start-notification) exercises ready and
delayed metadata, process exit, invalid PID content, and permanent file errors.
It passed on x86-64 and aarch64 under QEMU; the unchanged negative control fails
the same required-notification assertion that the patch passes. Run it with the
pinned upstream 1.19.0 archive:

```sh
python3 docs/upstream/flatpak/test-start-notification /path/to/flatpak-1.19.0.tar.xz
```

The [commit-boundary harness](test-start-notification-history) compiles production
constructors and callbacks from the exact parent and introducing commit:

```sh
python3 docs/upstream/flatpak/test-start-notification-history /path/to/flatpak-clone
```

| Source | Ready metadata | Delayed PID metadata |
| --- | --- | --- |
| Parent `104ed5db5ee42c55139fbeaa5e9bcf3b8e670bec` | One startup signal | One startup signal |
| Commit `21f413f17f241240c5c5d67b0ac61c4bb7504075` | One startup signal | No startup signal |
| Commit plus proposed patch | One startup signal | One startup signal |

These focused harnesses use real GLib callbacks, timers, and temporary PID
files. Other metadata handling and D-Bus delivery use test doubles. They are
not a historical full-build bisection or an upstream integration test. Full
results are in [validation/commit-boundary.json](validation/commit-boundary.json).

The harnesses require Python 3, a C compiler, `pkg-config`, GLib/GIO
development headers, and `patch`; the history harness also requires a full
Flatpak git clone. They create temporary files and executables without
modifying the source checkout or system services.

## Remaining work and provenance

The patch is proposed for review. Upstream acceptance, coverage in Flatpak's own
test suite, Fedora packaging, and validation after installing a fixed package
remain to be tracked separately. A matching report or fix was not found in the
official tracker searches on 8 September 2026; absence from those searches is
not proof that no duplicate exists.

The investigation, patch, test harnesses, and report were developed with AI
assistance through Codex. The measurements above distinguish recorded program
output, source-level tests, and the device owner's visual confirmation. The
source references and reproducible controls are provided for independent
review.
