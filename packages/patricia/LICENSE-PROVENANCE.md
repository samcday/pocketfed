# License provenance for the downstream Rust package

Prototype upstream commit: `552c652c75c4d32640e90d702862b93f7e275f2b`
Original licensed downstream base: `cdab42d9b93a0b33070804b37098568c3a3227f8`
Repository: <https://gitlab.com/InsanePrawn/android-patricia-dict>

On 2026-09-07 the PocketFed maintainer relayed the author's confirmation that
the Rust implementation is GPL version 3 only, and explicitly authorized
working under that confirmation with a downstream metadata delta while the
maintainer coordinates the upstream change.

The prototype carries that same author-declared license metadata forward to
the newer upstream Rust implementation. Both pinned upstream revisions still
lack a license file or Cargo license field. This is a record
of author confirmation relayed by the maintainer, not a claim that an upstream
license file or Cargo field was verified. The downstream package adds
`license = "GPL-3.0-only"` to Cargo.toml and supplies the unmodified GPL version
3 text as COPYING. No Rust behavior is changed by this delta.

The published Git checkout retains the original C++ tree and dictionary
fixtures with their existing notices. The separately prepared PocketFed Rust
source archive contains only the crate source, manifest, lockfile, README and
downstream notices, and omits that C++ tree and all dictionary fixtures. Dictionary data is packaged independently with
its own provenance and terms.
