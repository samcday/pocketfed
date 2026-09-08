# Patricia dictionary integration inventory

The current assessment pins `android-patricia-dict` to
`cdab42d9b93a0b33070804b37098568c3a3227f8`, committed on 2026-09-07.
Upstream force-updated `main` during this work. This inventory supersedes the
earlier assessment of `644366a1e98b8095d754e39c1bfc203d625b3a2c`.

Repository: <https://gitlab.com/InsanePrawn/android-patricia-dict>

## API available at this commit

The crate reads Android/HeliBoard Patricia formats 2/201/202, 402 and 403.
The v2 and v402 backends are read-only; v403 supports dictionary creation,
word updates, and adding/removing ngrams. The update adds:

- Bigram context on v2/v402 and up to quadgram context on v403.
- `query_with_context`, `probability_of`, `ngrams_for`, `ngram_scores`, and
  prepared-context batch scoring (`prepare_context`, `score_candidates`).
- `traverse_nodes` with continue/prune/stop visitor control for future gesture
  filtering, alongside prefix/suffix/length/start/end filters.
- v2 shortcut targets, including correction expansions such as `alot` to
  `a lot`, through `shortcuts_for` and optional search output.

Contexts are chronological (oldest first), retaining the newest representable
suffix. Per-order scores expose raw stored bytes and leave score mixing to
the caller. Writes require explicit probabilities; there is no automatic
learn-from-text policy. Search limits are traversal limits, not ranked top-N.

Search now includes not-a-word and blacklisted terminals by default to match
the reference engine. Completion must explicitly use
`with_include_not_a_word(false)` and `with_include_blacklisted(false)`.
Spelling correction can inspect these entries and shortcuts intentionally.
The crate still does not itself implement approximate spelling search,
language selection, composition, or a D-Bus service.

## Packaging prerequisites

The PocketFed maintainer relayed the author's confirmation of GPL version 3
only on 2026-09-07 and authorized a downstream license metadata change. The
pinned upstream files still lack a top-level Rust license declaration. See
[LICENSE-PROVENANCE.md](LICENSE-PROVENANCE.md) for this distinction. The
reproducible `prepare-source` script adds the Cargo SPDX field and GPL3
`COPYING` to a curated Rust-only archive, excluding the retained Android C++
tree and dictionary fixtures. Its checksum is in `sources.sha256`.

Runtime dependencies remain `memmap2`, `byteorder`, and `thiserror`; test
dependencies are `tempfile`, `assert_cmd`, and `predicates`. The Rust crate
does not require the retained C++ code at runtime.

The repository includes English, German, and Belarusian binary fixtures,
plus generated v402/v403 derivatives. The English fixture was verified as
byte-identical to `dictionaries/main_en_us.dict` at the separately pinned
Helium314/aosp-dictionaries commit. See `../keyboard-dictionaries/` for data
source, checksums and notices. German and Belarusian fixtures remain excluded
from the curated package pending their own per-file review.

## Initial dictionary plan

The trial uses the normal US English Patricia dictionary supplied by
Helium314/aosp-dictionaries, packaged independently as
`android-patricia-dictionaries-en-US` at
`/usr/share/android-patricia-dictionaries/en_US.dict`. It includes 160,715
source word entries, 481,875 bigram records and 99 shortcut records. The
source wordlist matches OpenBoard v1.4.5 after decompression. These stored
scores are not a promise of suggestion quality on modern text.

Hunspell and SCOWL conversion remain possible comparisons; the initial
runtime path is the Patricia backend in Verbisage, as requested.

## Verification

The unmodified pinned update passed 77 upstream tests on x86_64: four unit
tests, 68 integration/benchmark tests, and five doc tests. This includes
ngram ordering, update/backoff, batch scoring, shortcuts and filtering.
These were source tests using the repository's included fixtures, not Fedora
RPM builds or proof of full Android binary compatibility. The public downstream fork is recorded in [downstream-fork.json](downstream-fork.json).

## Reproduce the standalone crate package

The standalone RPM builds against Fedora's Rust crate packages. It produces
`rust-patricia_dict-devel`, default-feature metadata and `patricia-dict-tools`
with a manual page and separate debug RPMs. The CLI's compound license is
computed from the statically linked crates; `LICENSE.dependencies` is shipped.
The source crate remains GPL-3.0-only under the recorded author confirmation.

```sh
packages/patricia/prepare-source \
  --output /tmp/patricia-sources/pocketfed-patricia-rust-gpl3-cdab42d9b93a0b33070804b37098568c3a3227f8.tar.gz
cp packages/patricia/patricia_dict_cli.1 /tmp/patricia-sources/
rpmbuild -ba \
  --define '_topdir /tmp/patricia-rpmbuild' \
  --define '_sourcedir /tmp/patricia-sources' \
  packages/patricia/rust-patricia_dict.spec
```

Install `cargo-rpm-macros` and the dependencies returned by the spec's dynamic
BuildRequires first, or let a Fedora build system resolve them. Passing
`--upstream-archive` to preparation uses a locally cached full source archive;
its checksum is verified before selecting the Rust files. Repeating preparation
produced the same curated source checksum.

The local Rawhide x86_64 standalone RPM build passed four unit tests and five
doc tests from the curated source. The upstream corpus suite listed above is
separate because those fixtures are omitted from the source RPM. The installed
CLI also verified the packaged dictionary's format and word count, a word
query and its stored shortcut. `validation.json` records the existing local build, lint results and artifact
hashes; raw local logs are not included.
