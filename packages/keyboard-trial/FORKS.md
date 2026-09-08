# Public downstream source

| Component | Public downstream branch | Pinned downstream commit | Upstream base |
| --- | --- | --- | --- |
| [Stevia](https://github.com/samcday/stevia) | `codex/pocketfed` | `455c9b4d30876ea20e80d643a517b128c1844e6c` | `v0.57.0`, `d45a7e0d156d885721dfba6ef390be77e165c766` |
| [Verbisage](https://github.com/samcday/verbisage) | `codex/pocketfed` | `040dd993ce21adeb97d93bcb16c25eda8767e865` | `97aabc197c4e08555bb716f910f614c7c6e601aa` |
| [Patricia reader](https://github.com/samcday/android-patricia-dict) | `codex/pocketfed` | `ba460455e692a1ece86ebf990027c3cfb1e413e4` | `cdab42d9b93a0b33070804b37098568c3a3227f8` |

These cross-host imports preserve upstream GitLab history. They are public
GitHub repositories, not GitHub fork-network entries or upstream merge requests.

- [Stevia comparison](https://github.com/samcday/stevia/compare/v0.57.0...codex/pocketfed): two implementation commits match the RPM patches; all 265 source files match the tested archive plus patches. `DOWNSTREAM.md` is additional documentation.
- [Verbisage comparison](https://github.com/samcday/verbisage/compare/97aabc197c4e08555bb716f910f614c7c6e601aa...040dd993ce21adeb97d93bcb16c25eda8767e865): all 47 curated implementation/build/data files match the frozen 1.2 sources. A public pinned Patricia submodule supplies the same 23 reader files. The public fork passed 73 Rust tests, two doctests, and private D-Bus fixture/corpus checks.
- [Patricia comparison](https://github.com/samcday/android-patricia-dict/compare/cdab42d9b93a0b33070804b37098568c3a3227f8...ba460455e692a1ece86ebf990027c3cfb1e413e4): license/provenance metadata and downstream documentation; the Rust implementation is unchanged. The 23 curated package files match.

The package recipes continue using the exact verified upstream inputs plus
patches or curated source preparation. Publishing these forks does not change
an SRPM Source URL, source hash, patch or release.

Drift Type remains pinned to its public Codeberg commit. Its only downstream
change corrects Cargo license metadata; no separate behavioral fork is needed.
The dictionary and compiler retain their independently pinned public source
repositories. Nothing has been submitted to those upstream projects.
