# Public downstream implementation

[The public fork](https://github.com/samcday/verbisage) uses branch
`codex/pocketfed`, commit `040dd993ce21adeb97d93bcb16c25eda8767e865`, based on
upstream `97aabc197c4e08555bb716f910f614c7c6e601aa`.

[Review the changes](https://github.com/samcday/verbisage/compare/97aabc197c4e08555bb716f910f614c7c6e601aa...040dd993ce21adeb97d93bcb16c25eda8767e865).
Its public Patricia submodule is pinned to
`ba460455e692a1ece86ebf990027c3cfb1e413e4`. All 47 curated Verbisage source files
and all 23 reader files match the tested 1.2 package source. The public fork
passed 73 Rust tests, two doctests and private D-Bus fixture/corpus checks.

The existing README is itself an RPM Source file and remains byte-identical.
This separate note records the public fork without changing that tested source
payload or switching the RPM's immutable upstream/repack recipe.
