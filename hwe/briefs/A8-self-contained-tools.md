# Brief A8: make the hwe tools independent of tools/liveboot

The branch was rebased onto `origin/main`, which no longer contains
`tools/liveboot/` (the harness is being replaced). `hwe/tools/*.py` and
`hwe/dt/tools/*.py` currently load helpers from it with
`importlib.util.spec_from_file_location(..., LIVEBOOT / "build-kernel.py")`
and friends, and `fedora-kernel-bundle.py` reads
`tools/liveboot/profiles/google-sargo-initrd.conf` for the early-module report.
Those paths do not exist any more, so the tools and their tests are broken.

Work only in `/var/home/sam/src/pocketfed-hwe` (branch `claude/hwe-stock-kernel`,
now one commit on top of `origin/main`). Write only under `hwe/` and `out/`. No
commits, no phone, no podman. The old helper sources are still reachable with
`git show 47ae272d:tools/liveboot/build-kernel.py`,
`git show 47ae272d:tools/liveboot/prepare-fixture.py`,
`git show 47ae272d:tools/liveboot/run.py` (read them that way; do not check
that commit out and do not recreate `tools/liveboot/`).

## Deliverables

1. `hwe/tools/hwe_common.py`: a single module holding copies of exactly the
   helpers the hwe tools use (from the grep: `sha`, `write_json`, `regular`,
   `relative`, `inventory`, `verify_kernel`, `verify_modules`, `Commands`,
   `build_environment`, `BuildError`, `FixtureError`, `canonical_kernel`
   (the zboot/gzip/zstd decoder), `early_modules`), plus whatever those
   transitively need. Keep function names and behaviour; note the source
   commit and file for each in a header comment. Do not copy unrelated code.
2. Replace every `spec_from_file_location` import of liveboot files in
   `hwe/tools/*.py`, `hwe/dt/tools/*.py` and their tests with imports from
   `hwe_common` (tools and tests live in different directories; use a small
   `sys.path` insertion relative to `__file__`, or `importlib` on the known
   path of `hwe_common.py`, consistently).
3. `fedora-kernel-bundle.py` and `bundle-add-kmods.py`: replace the hardcoded
   early-module config path with an optional `--early-modules <conf>` argument
   (the same `force_drivers`/`add_drivers` shell-fragment format). Without it,
   skip `early-modules.txt` and say so in the log. The Sargo list is available
   untracked at `out/hwe/liveboot/google-sargo-stock-initrd.conf` for testing.
4. Run every test: `hwe/tools/test-*.py`, `hwe/dt/tools/test-*.py`. Then prove
   the real path still works: rebuild
   `out/liveboot/candidates/stock-rawhide-73rc3-08` from `out/hwe/rpms` with
   `--early-modules out/hwe/liveboot/google-sargo-stock-initrd.conf`, add the
   kmods from `hwe/kmods/sdm670-early` (name `sdm670-early`) into `-09`, set
   the DTB `out/hwe/A4/sdm670-google-sargo.debug-uart.dtb` (sidecar
   `out/hwe/A4/compose.json`) into `-10`, and diff `-10/bundle.json` against
   `out/liveboot/candidates/stock-rawhide-73rc3-05/bundle.json`: the image,
   dtb and module_files sha256 sets must be identical. Full logs under
   `out/hwe/A9/`, never summarised through tail/grep.
5. Update `hwe/PLAN.md` "Working agreements" and the tool docstrings so nothing
   claims a dependency on `tools/liveboot`.

## Report

`out/hwe/A9/REPORT.md`: files changed, exact commands, test results with log
paths, the bundle equivalence result, anything skipped. Stop after writing it.
