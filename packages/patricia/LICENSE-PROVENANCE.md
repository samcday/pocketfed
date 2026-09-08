# License provenance for the downstream Rust package

Upstream commit: `cdab42d9b93a0b33070804b37098568c3a3227f8`
Repository: <https://gitlab.com/InsanePrawn/android-patricia-dict>

On 2026-09-07 the PocketFed maintainer relayed the author's confirmation that
the Rust implementation is GPL version 3 only, and explicitly authorized
working under that confirmation with a downstream metadata delta while the
maintainer coordinates the upstream change.

The pinned upstream files do not yet declare that license. This is a record
of author confirmation relayed by the maintainer, not a claim that an upstream
license file or Cargo field was verified. The downstream package adds
`license = "GPL-3.0-only"` to Cargo.toml and supplies the unmodified GPL version
3 text as COPYING. No Rust behavior is changed by this delta.

The curated archive contains only the Rust crate source, manifest, lockfile,
README, and these downstream notices. It omits the retained Android C++ tree
and all dictionary fixtures. Dictionary data is packaged independently with
its own provenance and terms.
