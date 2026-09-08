# Verbisage Patricia service

This downstream trial builds Verbisage commit
`97aabc197c4e08555bb716f910f614c7c6e601aa` with the Patricia reader at
`cdab42d9b93a0b33070804b37098568c3a3227f8`. It supplies the `verbisage` client
and the on-demand `org.verbisage.Dictionary` session D-Bus service.

The default backend reads the separately packaged
`/usr/share/android-patricia-dictionaries/en_US.dict`. The runtime dependency is
`android-patricia-dictionaries-en-US`; Hunspell is disabled in this build.
The default config is `/etc/verbisage/config.toml`. An existing
`$XDG_CONFIG_HOME/verbisage/config.toml` (or `~/.config/verbisage/config.toml`)
takes precedence. The service needs no privileged/system bus access.

The patch maps Patricia word scores to Verbisage's 0–1 ranking scale, excludes
blacklisted and not-a-word entries from completions, and uses Patricia's ngram
APIs directly for next-word prediction. Stored probabilities are not treated
as corpus counts. Corrections retain Verbisage's English one-edit candidate
generator. This is a usable integration trial, not a claim of complete
Android correction behaviour. System dictionary writes and learning are
unsupported. Stevia owns preedit/candidate selection and the gesture UI.

`Complete(s word, u max, s lang)` returns `a(sd)`: one ranked response for
current-word prefix expansions and single-edit corrections. The frontend owns
the exact literal; Complete omits case-equivalent exact input. Maximum output
is 100. Empty or whitespace input and zero max return no results. Input is
limited to 128 Unicode characters / 512 UTF-8 bytes; control characters and
oversized input return InvalidArgs. Existing language validation still applies.

Ranking combines the highest `max + 1` prefix matches (at most 101) with every
usable single-edit candidate, then deduplicates and truncates. Match weights
are 1.0 for intact prefixes, 0.9 for adjacent transpositions and missing/extra
doubled letters, 0.65 for other insertions/deletions, and 0.5 for substitutions.
Each weight is multiplied by `ln(1 + frequency)` normalized by the highest
candidate prior. Nonfinite/negative frequencies are treated as unavailable;
when all priors are unavailable, match weights determine order. Equal scores
sort lexically. These are heuristic ranking scores, not calibrated probabilities.
The logarithm accepts both Patricia ranks and SQLite counts, but their scales
differ; this is a practical shared rule rather than a fitted language model.

Known words and fragments shorter than three characters receive only prefix
expansions. Initial-capital and all-capital forms also count as known words,
so a proper name such as Linux does not become a typo correction simply
because the frontend sends lowercase. Prefix vocabulary lookup still follows
the backend's case behavior. Insertions/substitutions use the existing English
a-z alphabet; there are no word-specific ranking exceptions. SQLite's bounded
query treats apostrophes, percent signs and underscores literally and limits
rows in SQL. Client-side stdio explicitly selects its transport even when the
installed daemon configuration selects D-Bus.

`QueryLimited(as prefixes, as suffixes, u min_len, u max_len, s lang, u max)`
returns `a(sd)`. Zero length bounds are unconstrained, zero max returns no
results, and max is capped at 100. The Patricia implementation streams matching
words and retains only the requested best results. The existing `Query`,
`Suggest`, `IsCorrect`, `Predict`, `Frequency`, `AddWord` and `BumpNgram` APIs
remain available. The latter two report unsupported operations for read-only
Patricia data. Invalid languages and missing dictionary data return errors.

## Sources and licenses

`prepare-sources` creates a deterministic source archive from the exact Git
commit, including only Rust/build code and D-Bus data. It excludes upstream's
bundled RPM, language models, planning notes and recorded conversations. Its
second archive contains the exact `Cargo.lock` dependencies and their original
notices for an offline build. `sources.sha256` pins all three archives.
The source files are uploaded in an SRPM, not downloaded during RPM builds.

Verbisage's manifest declares `MIT OR Apache-2.0`; this package selects
Apache-2.0 and supplies its standard license text, with no invented copyright
holder. Patricia's author confirmed **GPL-3.0-only**, relayed by the user on
2026-09-07. The curated reader archive records this downstream license delta
in `LICENSE-PROVENANCE.md`; it does not claim the pinned upstream checkout
already contained a license. See `../patricia/` for its repack recipe.
The binary license expression incorporates the linked GPL-3.0-only reader.

The Fedora Rust macros generate `LICENSE.dependencies` with exactly the build
features (`--no-default-features --features sqlite,dbus,patricia`) and generate
`cargo-vendor.txt` for automatic `bundled(crate(...))` Provides. Distributed
vendor notices are included in the binary RPM. No Rust development package or
C ABI/shared library is shipped. `vendor-licenses.json` inventories the entire
vendor source archive, including optional and build-only dependencies.

## Rebuild and checks

Generate the Patricia archive with the recipe in `../patricia/`, then:

```sh
packages/verbisage/prepare-sources \
  --checkout /path/to/pinned/verbisage-checkout \
  --patricia-archive /path/to/pocketfed-patricia-rust-gpl3-cdab42d9b93a0b33070804b37098568c3a3227f8.tar.gz \
  --output /path/to/srpm-sources
```

Omit `--checkout` to clone the public repository. `--cargo` and `--cargo-home`
can select a build toolchain/cache. Check `sources.sha256` in the output folder,
then copy the local spec Sources and patch there and build the SRPM normally.
The package builds with Fedora's Cargo macros, system SQLite, and offline
vendored dependencies. It needs Rust/Cargo, cargo-rpm-macros, GCC, sqlite-devel,
dbus-daemon, Python and python3-gobject-base.

The RPM runs all enabled Rust tests and an isolated real-daemon D-Bus test for
ranking, bounds and unavailable-language errors. An additional corpus test:

```sh
dbus-run-session -- packages/verbisage/test-dbus.py \
  --daemon /usr/bin/verbisaged \
  --patricia-dict /usr/share/android-patricia-dictionaries/en_US.dict
```

The production Stevia completer is tested against this service separately in
`packages/stevia/`; its fake-service tests cover delayed, stale and failed
requests independently of dictionary contents.
