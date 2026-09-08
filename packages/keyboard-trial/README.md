# Keyboard completion packages

These six source packages make the tested English current-word completion
stack reproducible in Fedora Rawhide. They are submitted through the main
[samcday/pocketfed COPR](https://copr.fedorainfracloud.org/coprs/samcday/pocketfed/).
The [publication record](PUBLICATION.md) links each build.
The runtime selection belongs only to the personal sam-sargo image. This change
does not alter shared PocketFed image allowlists, defaults or deployment state.

| Source directory | Role |
| --- | --- |
| [stevia](../stevia/README.md) | Keyboard, preedit and candidate UI; opt-in Verbisage adapter |
| [verbisage](../verbisage/README.md) | Session D-Bus language service with Patricia and ranked `Complete` |
| [keyboard-dictionaries](../keyboard-dictionaries/README.md) | Reproducible English Patricia dictionary data |
| [patricia](../patricia/README.md) | Reader crate and developer CLI |
| [drift-type](../drift-type/README.md) | Gesture-decoder source crate for later integration |
| [rust-embed-doc-image](../rust-embed-doc-image/README.md) | Drift documentation build dependency |

The runtime set is `stevia`, `verbisage`, and
`android-patricia-dictionaries-en-US`. The source/development packages do not
need to be installed on the phone. Drift is packaged but swipe typing is not
implemented. Verbisage remains an explicit backend choice in Stevia.

The specs, patches and RPM Source files preserve the already-tested package
inputs: Stevia/Verbisage release `1.2.pocketfed`, with the same pinned dictionary,
Patricia and Drift development packages. Their immutable upstream inputs and
checksums remain in each package directory. Public implementation forks are
listed in [FORKS.md](FORKS.md); the RPMs still use the verified upstream archive
plus downstream patch/repack recipe, rather than silently changing sources.

The package READMEs explain source preparation. Builds consume complete SRPMs;
network fetching belongs to preparation, not `%build` or `%check`. Use clean
Fedora Rawhide buildroots and resolve their generated BuildRequires. Aggregate
checks are in [VALIDATION.md](VALIDATION.md); each spec runs its own checks.

For a private-bus current-word corpus/latency check:

```sh
dbus-run-session -- python3 packages/keyboard-trial/benchmark-complete.py \
  --daemon /usr/bin/verbisaged \
  --dictionary /usr/share/android-patricia-dictionaries/en_US.dict \
  --output /tmp/complete-benchmark.json
```

This reports dictionary service round trips, excluding frontend debounce,
rendering and physical touch. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
current boundary and [NEXT.md](NEXT.md) for the proposed gesture milestone.
Only portable source/tests and public provenance are kept here; local build
outputs, device snapshots, credentials, installation state and logs are excluded.
