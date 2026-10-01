# Validation summary

Concise public summary of the paired client/service validation behind this
handoff. Raw logs, device snapshots, private Drift Type source and internal
provenance directories are intentionally not published.

- **18 real-service paired cases passed** (frozen Stevia client + Verbisage
  service).
- **18 controlled-native cases passed** against the controllable stand-in.
- Invalid native attempts are retained: `typed-reselect` could not start Phoc
  with an overlong Unix socket path; two stand-in `language-transition-undo`
  attempts lacked the required correction candidate. Their corrected runs
  passed. A coordinator error hashing a directory-based Patricia dictionary
  also stopped one attempt before native startup; the corrected run passed.

These are protocol/geometry and service-integration checks. They do **not**
establish human spelling, gesture or multilingual accuracy, and no physical
device has been run.

## Identities

| Component | Identity |
| --- | --- |
| Client source | `samcday/stevia` `7a00a8fff38ac60d7998a8cc7ec88c6111d4f304` (`codex/layout-integration`) |
| Tested client binary (x86_64) | `f2044971cfdddbbcbc5c4204d3124f62a2966382fce6362226e0eae24de1d020` |
| Service source / runtime | `samcday/verbisage` `d7012120bfcacb22dc55eb9009c28a3afe985aac` |
| `verbisaged` / `verbisage` (x86_64) | `008f23c2e67d8b0c70ed430292b91e5067573ddeeb5b1244fd20530ccb816a25` / `a051b2de4eda030623cb2095136b0e8727ebde341f96ee9ac2691c779e05f52c` |
| Layout library | `samcday/rs-keyboard-layout` `d60e05ce20b77a84ec4ac3a8c38b1c295dfa38fe` |
| Patricia reader | `samcday/android-patricia-dict` `32121e2b5cb8615d408eecc9cd55eeb8d51bd7b7` |
| Gesture crate (private) | `f0b2cc7ac1f84d479abfa6c8e4028f473a8c50b3` (source not published) |
| Controlled-service harness `run-context.py` at7a00a8f | `e485342aa54f678fe9f9fba2cd97a3ea1bc1c2d1ad4bbe36d0f4a3f178855172` |
| Frozen real-service harness `run-context.py` at8f8b6bd | `b53eff612d02ada539a8598c26061dddfd1fdfb61a2860149cdcc528b91e11d9` |
| Stand-in `fake-verbisage.py` | `eec6372560e50e1d555329f6f4958802d79fb19c8385e594c598104080b39895` |
| Probe `gtk4-polish-probe.py` | `0ea2940fdc84f83f79b1e3ee1039698dfdb395735ec21f7b267ca06789602e39` |
| OSK schema `mobi.phosh.osk.gschema.xml` | `16d91cf9da3b96141d6613ff9f054303f26913d544c75512357d1bd46a76833a` |
| Generated `mobi.phosh.osk.enums.xml` | `8cafc664b00e1839274e76bd8dab23a42f70d6f855feedc1b3f37562bce5643b` |

The client commit changes only the Python native harness; the runtime C source
is unchanged from the tested parent `8f8b6bd…`, and build hashes are
path-dependent. Public harness and fixture source:

- [Stevia native harness](https://github.com/samcday/stevia/blob/7a00a8fff38ac60d7998a8cc7ec88c6111d4f304/tests/native/run-context.py)
  and [stand-in](https://github.com/samcday/stevia/blob/7a00a8fff38ac60d7998a8cc7ec88c6111d4f304/tests/native/fake-verbisage.py)
- [Exported US normal fixture](https://github.com/samcday/verbisage/blob/d7012120bfcacb22dc55eb9009c28a3afe985aac/tests/fixtures/layout-us-normal.json)
  (`32dbc4e6f0df7b1f42324f9cecfbd623402fd62734feac2a76738d4808ed0f1f`)
- PRs: [stevia#1](https://github.com/samcday/stevia/pull/1),
  [verbisage#1](https://github.com/samcday/verbisage/pull/1),
  [rs-keyboard-layout#1](https://github.com/samcday/rs-keyboard-layout/pull/1)

## 18 real-service paired cases

| Group | Cases |
| --- | --- |
| First native set (4) | `swipe`, `swipe-shift`, `typed-undo`, `swipe-next` |
| Remaining native (7 passed) | `swipe-tap`, `swipe-undo`, `swipe-edit`, `swipe-focus`, `undo-focus`, `literal`, `swipe-rapid` |
| Short-path rerun (1) | `typed-reselect` |
| SQLite context (3) | `context-chain`, `context-prefix`, `context-undo` |
| Patricia context (1) | `context-swipe` |
| Language transition (2) | `language-transition-undo`, `language-transition-undo-control` |

The first `typed-reselect` run is the preserved invalid case (Phoc headless
Unix socket path too long); the short-path rerun passed. In the language pair
both the focused check and its sibling control passed against the real service.

Swipe trail pixel energies in the paired evidence: released `451815`,
decaying `234850`, cleared `0`.

## 18 controlled-native cases (stand-in)

- Round 08 (5): `queue-geometry`, `queue-overlap`,
  `queue-reverse-barrier`, `queue-middle-failure`,
  `queue-job-deadline-busy`.
- Round 09 (13 passed): `queue-overflow`, `queue-enter-suffix`,
  `queue-backspace-utf8-suffix`, `queue-backspace-hold`,
  `queue-pending-ack-reset`, `queue-ack-expiry-last-key`,
  `queue-field-switch`, `queue-hide`, `queue-cursor-move`,
  `queue-middle-timeout`, `queue-job-deadline-late-playback`,
  `language-routing`, `language-dvorak`.

The stand-in answers `CompleteWith`/`PredictWith` with an empty list and so is **not a
language corpus**; its `language-transition-undo` attempt (r14, retried r15)
deterministically failed with `Completion 'hello' is not offered; visible:
['helo']`. That is a stand-in capability limit, not a product defect, and no
assertion was weakened. The same case passed against the real service in the
language pair above.

## Caveats

- Controlled-native cases exercise the stand-in protocol, not language
  accuracy. The exported fixture is geometry acceptance, not human touch.
- No physical device acceptance, no aarch64 run, no learning, user/system
  interleaving, frequency decay or raw tap capture. System dictionaries are
  immutable. Synthetic fixtures do not prove human or multilingual accuracy.
- No universal no-loss claim for unconfirmed edits.
