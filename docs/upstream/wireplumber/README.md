# WirePlumber: role loopbacks can cork music after output reconnection

When the only audio output disappears, WirePlumber can connect a role
loopback's output to another role sink. That link inherits the target role's
priority and can cork music. The link can survive reconnection, leaving music
without playback links after the real output returns.

This was observed with WirePlumber 0.5.14 on Fedora desktop and phone systems,
then reproduced using a complete upstream 0.5.17 build and its own example
role configuration. The problem requires role-based routing to be enabled.
No first-bad commit or first affected release has been established; this is
an upstream bug candidate, not an attributed new Rawhide regression.

## Proposed correction

The [production patch](wireplumber-prevent-role-loopback-chaining.patch)
adds 15 lines to `linking-utils.lua`'s shared `canLink()` check. It rejects a
role-policy target if the source's link group already contains a role-policy
target. This covers default and fallback target selection while preserving
ordinary clients, filters, monitor streams, and routing to hardware.

The [separate test patch](wireplumber-test-role-loopback-routing.patch) covers
these eligibility cases. Existing graph-cycle prevention remains intact:
a link into a higher-priority role can cause this failure without a cycle.

The tested upstream base is
[`7c3bf214b7026ff7bb32e94d7489dcadbc4580b5`](https://gitlab.freedesktop.org/pipewire/wireplumber/-/commit/7c3bf214b7026ff7bb32e94d7489dcadbc4580b5),
which identifies itself as 0.5.17. Patch commits are `f65ea7c4e709` (fix) and
`5df6741803e7` (test). On 2026-09-08 both patches also passed `git apply --check`
against the affected files from current upstream master
[`2649ebb4dc37760ed220cb579f4b409c466804e8`](https://gitlab.freedesktop.org/pipewire/wireplumber/-/commit/2649ebb4dc37760ed220cb579f4b409c466804e8).
That applicability check is not a build or runtime test of the newer revision.

## Reproduce and validate

The [Python reproducer](wireplumber-role-hotplug.py) starts its own PipeWire
server, WirePlumber process, session bus, silent player, and null sink. It
disables hardware discovery and uses the checkout's example
`media-role-nodes.conf`. It requires Python 3, PipeWire and its CLI tools,
`dbus-run-session`, and the dependencies for building WirePlumber. No feedbackd
daemon, Bluetooth device, display hardware, or suspend operation is needed.

Download this directory's two patches and reproducer next to a clean
WirePlumber checkout. From that checkout:

```sh
git checkout 7c3bf214b7026ff7bb32e94d7489dcadbc4580b5
meson setup build -Ddoc=disabled -Dintrospection=disabled
meson compile -C build
python3 ../wireplumber-role-hotplug.py --upstream-tree "$PWD" --expect stall

git am ../wireplumber-prevent-role-loopback-chaining.patch \
  ../wireplumber-test-role-loopback-routing.patch
meson compile -C build
meson test -C build test-linking-role-loopbacks
python3 ../wireplumber-role-hotplug.py --upstream-tree "$PWD" --expect recovery
```

`--expect stall` succeeds only when it observes the original failure.
`--expect recovery` checks three output reconnects, then verifies that a
Communication stream corks music and that music resumes when it ends.
Optional `--artifact-parent /short/path` changes the location of isolated
runtime directories and logs; keep the path short for Unix sockets.
The reproducer stops its child processes when finished.

Recorded validation on 2026-09-07 used x86_64 Fedora 44, PipeWire 1.6.8,
GLib 2.88.3, bundled Lua 5.5.0, and GCC 16.1.1:

| Check | Original source | Patched source |
| --- | --- | --- |
| Complete upstream build, remove/recreate null output | Persistent cross-role links; music unlinked | Three reconnects recover with active stereo music links |
| Communication priority after reconnect | Not part of the baseline stall run | Music corked, then resumed |
| New regression test | Fails without the guard | Passes with the guard |
| Full Meson suite | 44/56 pass | 45/57 pass; same 12 failures |

The [validation summary](validation-summary.json) contains per-test outcomes,
the relevant synthetic graph links, and the before/after regression-test
results extracted from the retained run artifacts. Source hashes identify the
original local artifacts. Extraction on 2026-09-08 independently checked the
three recovery snapshots, priority/resumption snapshots, original stall, and
identical failure sets. These are recorded runs, not freshly rerun integration
tests. Full logs contain inherited environment and client metadata; those
fields are omitted from the public summary.

The twelve baseline failures cover nine capture-linking tests, initial
default metadata, dynamic rules, and `si-node`. Their cause remains unresolved.
The comparison demonstrates no additional failures in this environment; it
does not establish an entirely passing upstream suite. Routing and stream
completion checks do not measure acoustic output or modem call quality.

## Upstream follow-up

As of the publication preparation on 2026-09-08, this patch series had not
been submitted upstream. It remains a proposed correction for review.
All-state upstream issue searches for `role` and `loopback`, and merge-request
searches for `role`, found related reports but no exact match for this
reproduced cross-role target/corking mechanism. This is a bounded duplicate
search, not a claim that no duplicate exists.

- [PipeWire #5082](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/5082)
  remains open and concerns output reconnection, media roles, and a
  latency-update/CPU loop. It was transferred from WirePlumber #889.
  This series does not claim to fix that CPU-loop report.
- [WirePlumber #499](https://gitlab.freedesktop.org/pipewire/wireplumber/-/issues/499)
  concerns missing loopback activation with the older 0.4 endpoint policy.
- [WirePlumber #687](https://gitlab.freedesktop.org/pipewire/wireplumber/-/issues/687)
  concerns smart-filter echo-cancel routing. Its reported setup does not
  establish the media-role priority failure reproduced here.
- [WirePlumber !866](https://gitlab.freedesktop.org/pipewire/wireplumber/-/merge_requests/866)
  and [!869](https://gitlab.freedesktop.org/pipewire/wireplumber/-/merge_requests/869)
  are merged bookkeeping fixes already present in the tested upstream base.

The [official contribution guide](https://pipewire.pages.freedesktop.org/wireplumber/resources/contributing.html)
uses the ordinary fork, branch, rebase, test, and merge-request workflow.
Upstream's [AGENTS.md](https://gitlab.freedesktop.org/pipewire/wireplumber/-/blob/2649ebb4dc37760ed220cb579f4b409c466804e8/AGENTS.md),
refreshed from the public API on 2026-09-08, explicitly specifies AI-assistance
attribution. Both patches already carry `Assisted-by: Codex:gpt-6-astra`.
This report and publication preparation also used Codex with GPT-6 Astra.
The submitter remains responsible for reviewing and understanding the change.

Follow-up is to submit or cross-reference the report in WirePlumber, refresh
testing against the submission revision, obtain review of the correction,
and track release/Fedora delivery. A user Lua override was trialled locally;
it is not a maintained package delivery. Retire that override when a verified
distribution fix is installed.
