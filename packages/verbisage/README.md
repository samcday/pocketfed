# Verbisage completion and swipe service

Release `0.1.0-1.3.pocketfed` packages the tested public
[Verbisage tree](https://github.com/samcday/verbisage/tree/codex/swipe-prototype)
at `bef0046a2b75c20f2a6ca202d603fcbddd3d3df0`. Patricia uses upstream
`552c652c75c4d32640e90d702862b93f7e275f2b`, via the licensed downstream tree
`c76e17ae04aa563fc683d03e61bd673b20ab863e`. Drift Type stays at unmodified
`f63256a5bb973b10a4e11e190cfbb105fc89da0a` Rust source.

The on-demand session service owns `org.verbisage.Dictionary`, interface
`org.verbisage.Dictionary1`, object `/org/verbisage/Dictionary`. `Complete`
returns ranked prefix and single-edit typo candidates. `RecognizeSwipe` accepts
`a(ddu)` trace points, `a(sdddd)` key rectangles, maximum results and language,
and returns ranked `a(sd)` words. Actual geometry and whole-path scoring come
from Drift Type; Patricia supplies a bounded candidate snapshot. One worker,
node/time/candidate limits and stale-response handling keep gesture work
bounded. The existing ordinary completion API is retained.

The read-only dictionary is separately packaged as
`android-patricia-dictionaries-en-US`; its bytes and license notices are
unchanged. Configuration remains `/etc/verbisage/config.toml` with per-user
configuration taking precedence. SQLite remains available and Hunspell is
disabled in this build. There is no system-bus access, dictionary download,
learning or automatic dictionary mutation. Gesture scope is English ASCII,
one whole word, with no preceding-word context.

## Rebuild

The deterministic source repack excludes upstream RPMs, models, planning/chat
files and dictionary fixtures. Exact sources and locked registry dependencies
are supplied in the SRPM for offline builds. The only packaging patches make
Drift a local path dependency and correct its Cargo license field; no Rust
behavior changes are introduced by packaging.

First use `../patricia/prepare-source` for its curated source, then run:

```sh
packages/verbisage/prepare-sources \
  --checkout /path/to/verbisage \
  --patricia-archive /path/to/pocketfed-patricia-rust-gpl3-552c652c75c4d32640e90d702862b93f7e275f2b.tar.gz \
  --drift-archive /path/to/drift_type-f63256a5bb973b10a4e11e190cfbb105fc89da0a.tar.gz \
  --output /path/to/srpm-sources
```

Omit `--checkout` to clone the public repository. `--cargo` and `--cargo-home`
select the preparation toolchain/cache. Copy the local spec Sources and patches
into the output directory, then build the SRPM with rpmbuild. Compare generated
`sources.sha256` with the recorded file. The spec uses Fedora Rust macros and
system SQLite with `--no-default-features --features sqlite,dbus,patricia,swipe`.
Its checks run the enabled Rust suite and a private real-daemon D-Bus fixture;
introspection must contain `Complete` and `RecognizeSwipe`.

## Source notices

Verbisage and Drift use Apache-2.0 for this package. Patricia's GPL-3.0-only
metadata reflects author confirmation relayed by the user; its provenance file
records that basis. Vendor notices and generated linked-dependency license
inventory are shipped. Both separately supplied path dependencies have explicit
bundled-component Provides and license files. Full upstream source contracts
are retained as `DOWNSTREAM.md` and `SWIPE.md`; Stevia owns current frontend
composition and candidate-selection behavior.
