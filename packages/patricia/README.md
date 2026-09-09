# Android Patricia dictionary reader

The current package pins upstream `552c652c75c4d32640e90d702862b93f7e275f2b`
through the [licensed public tree](https://github.com/samcday/android-patricia-dict/tree/codex/swipe-prototype)
at `c76e17ae04aa563fc683d03e61bd673b20ab863e`. This is the same reader used by
the tested Verbisage swipe integration. No downstream Rust behavior changes
were needed. `LICENSE-PROVENANCE.md` records the author-confirmed GPL-3.0-only
metadata carried by the fork.

The newer upstream code adds migration/compaction, historical word data and
dynamic probability handling. Verbisage continues to use the same read-only
English corpus; this update does not migrate user dictionaries or enable
learning. The standalone package supplies library source/default-feature
metadata and `patricia-dict-tools`. The separately vendored Verbisage build
uses identical reader source.

`prepare-source` archives only Cargo files, Rust source, README and license
notices from the pinned commit. The retained C++ reference tree and dictionary
fixtures are excluded. It can use an existing Git checkout or fetch the exact
public commit:

```sh
packages/patricia/prepare-source \
  --checkout /path/to/android-patricia-dict \
  --output /path/to/pocketfed-patricia-rust-gpl3-552c652c75c4d32640e90d702862b93f7e275f2b.tar.gz
```

Copy `patricia_dict_cli.1` beside that archive and build the spec normally.
COPR resolves dynamic Fedora Rust BuildRequires and runs the curated unit/doc
tests. Corpus-dependent upstream tests remain separate because their fixtures
are not shipped. The source trial passed 95 upstream tests with two optional
interop/slow cases ignored; previous release records in `validation.json` are
historical. Current source pins and hashes are in `upstream.json` and
`sources.sha256`. English data provenance is maintained independently in
`../keyboard-dictionaries/`.
