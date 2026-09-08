# Initial whole-word swipe prototype

This prototype connects Stevia's real key geometry and touch path to Drift Type
inside Verbisage, using the English Android Patricia dictionary. It is separate
from the stable completion RPMs and personal image. Shared PocketFed images do
not include it.

The public source branches are:

- [Stevia](https://github.com/samcday/stevia/tree/codex/swipe-prototype):
  opt-in gesture capture, cancellation, explicit candidate selection and a
  trail whose segments fade over 1.5 seconds.
- [Verbisage](https://github.com/samcday/verbisage/tree/codex/swipe-prototype):
  one bounded `RecognizeSwipe` request per completed gesture, with Drift Type
  scoring and a request-local Patricia candidate snapshot.
- [Patricia](https://github.com/samcday/android-patricia-dict/tree/codex/swipe-prototype):
  upstream `552c652c75c4d32640e90d702862b93f7e275f2b` plus licensing/provenance
  metadata. No downstream Rust behavior changes were needed.

Drift Type remains pinned to upstream
`f63256a5bb973b10a4e11e190cfbb105fc89da0a`, without code changes. Its upstream
contribution restriction is respected; no generated submission was sent there.
Build instructions and the full wire contract are in the source forks' swipe
documents.

## Scope

Start a new word in an English-US normal text field, using the lowercase
alphabet layout and Verbisage completion. Drag across the letters, lift, then
select a candidate. The prototype does not automatically insert a result.
Ordinary tap typing remains available. Other languages, uppercase/symbol layers,
mixed tap/swipe words and automatic correction are future work.

The dictionary search is bounded by node count and elapsed time, and the daemon
permits one gesture worker at a time. A failed or canceled request leaves the
application text unchanged. No UI gesture traces are recorded or learned.

## Temporary device trial

[LIVE-TRIAL.md](LIVE-TRIAL.md) documents the manifest-fed helper. It accepts
only the known stable 1.1/1.2 runtime bytes or an identical prototype, then uses
an ephemeral `/usr` overlay. Its schema default enables swipe for the trial
without writing saved keyboard preferences. Reboot discards the trial and
boots the selected deployment normally, including any previously staged image.
The prototype binaries are source-built and unsigned, not COPR RPM updates.

`test-live-swipe.py` exercises manifest and file rejection, staging preservation,
schema compilation and recovery from a partial file replacement. These tests
use temporary files and do not modify the host keyboard.

## Integration checks

`validation/run-swipe.py` runs a separate headless Phoc, GTK4 field, Stevia and
Verbisage on a private bus. Its synthetic pointer drag drives the actual
keyboard widget; screenshots verify that the trail visibly fades and clears.
The tests check explicit word commitment, no crossed-key letters, focus loss
and ordinary taps. The helper sources and protocol are in
`../../stevia/validation/`; `virtual-drag.c` extends that test setup for drags.

On devices without Pillow, `--defer-pixel-check` leaves the swipe case marked
pending until `validation/verify-trail.py` checks the captured PNGs on a host.
It creates a separate verified result tied to the input result and image hashes.

The service replay uses ten synthetic words with ideal, perturbed and transformed
paths. The initial decoder finds 29 of 30 targets in the top two; the perturbed
`swipe` path remains a known miss. These checks establish integration behavior,
not recognition accuracy across people or real finger paths. Device-specific
records, package-state snapshots and raw logs are kept outside this public guide.
