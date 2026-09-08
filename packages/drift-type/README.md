# Drift Type crate packaging

This package prepares Drift Type for later swipe-input integration. It supplies
Rust source development packages; installing it does not enable swipe typing
in Stevia. The first Verbisage trial can run without Drift Type.

The source is pinned to upstream commit
`f63256a5bb973b10a4e11e190cfbb105fc89da0a` (2026-09-04), version `0.0.0`.
The API is experimental. `sources.sha256` records the upstream archive digest;
the spec uses the immutable commit archive rather than a moving branch.

The upstream `LICENSE` is Apache-2.0. The only downstream patch corrects
`license-file = "Apache-2.0"` (a nonexistent filename) to the SPDX
`license = "Apache-2.0"` field. Source and runtime behavior are unchanged.
No dictionaries or separately downloaded gesture corpora are included.
The source archive includes upstream documentation images and synthetic
word/gesture examples in its tests, under the repository's license.

The spec was checked against `rust2rpm 28` output for a local `cargo package`
archive with the metadata correction. Regenerate that baseline for each new
crate version; preserve the immutable upstream source and RPM snapshot release.
The spec follows Fedora Rust crate packaging conventions: source development
subpackages, generated dependency requirements, repository-provided crate
dependencies, and upstream unit/doc tests in `%check`. There is no vendored
dependency archive. `doc-images` is a feature subpackage and is tested alongside
the default feature set. Dependencies are `unicode-segmentation`, `regex`,
`log`, and `embed-doc-image`; the last is used for documentation images.

Drift's candidate interface currently borrows word strings from a persistent
dictionary. Patricia yields owned strings; a future adapter must retain those
strings or coordinate an upstream API change. Its separate language-model
interface can use Patricia's prepared context scores through Verbisage. Do not
introduce one D-Bus round trip per candidate or trie node.

Upstream's `CONTRIBUTING.md` requires human-written submissions and rejects
LLM-generated code, reports, and comments sent to the project. This directory
contains downstream packaging only; nothing has been submitted upstream.

To prepare an SRPM, download the source into an empty source directory, verify
`sources.sha256`, copy the patch there, and run:

```sh
rpmbuild -bs \
  --define "_sourcedir /absolute/path/to/sources" \
  --define "_srcrpmdir /absolute/path/to/output" \
  packages/drift-type/rust-drift_type.spec
```

Use a clean Fedora buildroot with `cargo-rpm-macros` and let the dynamic
BuildRequires resolve packaged Rust dependencies. Publication and phone
installation are separate steps; neither is implied by this package.

See `validation.json` for the checks actually completed.

The local Fedora Rawhide x86_64 RPM build passed all 59 unit tests and 16
documentation tests with both default and all features. `rpmlint` reports
zero errors and warnings. `../rust-embed-doc-image/` supplies the only missing
Fedora crate dependency; its RPM was installed in the builder for these checks.
