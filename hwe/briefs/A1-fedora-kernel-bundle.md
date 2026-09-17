# Brief A1: kboop candidate bundle from Fedora kernel RPMs

Read `hwe/PLAN.md`, `AGENTS.md`, `tools/liveboot/README.md`,
`tools/liveboot/build-kernel.py` and `tools/liveboot/prepare-fixture.py` first.
Work only in this checkout (`/var/home/sam/src/pocketfed-hwe`, branch
`claude/hwe-stock-kernel`). Write only under `hwe/` and `out/`. Do not touch
the phone, podman, git remotes, or anything outside this checkout. Do not
commit; leave the changes in the working tree.

## Deliverable

`hwe/tools/fedora-kernel-bundle.py` (Python 3, stdlib plus whatever
`tools/liveboot/*.py` already use). It turns an already-downloaded set of
Fedora aarch64 kernel RPMs into a kboop version-1 candidate bundle that
`just liveboot-prepare --kernel-bundle <dir>/bundle.json` accepts.

Input RPMs are in `out/hwe/rpms/`:

```
kernel-core, kernel-modules-core, kernel-modules, kernel-modules-extra,
kernel-modules-internal, kernel-devel   (all 7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64)
```

Usage to support:

```
/usr/bin/python3 hwe/tools/fedora-kernel-bundle.py \
  --rpm-dir out/hwe/rpms \
  --output out/liveboot/candidates/stock-rawhide-73rc3-01 \
  --dtb qcom/sdm670-google-sargo.dtb
```

Behaviour:

1. Extract the RPMs with `rpm2cpio | cpio` (host tools; no rpm install,
   no root). kernel-devel is not needed for the bundle; ignore it unless a
   check needs `Module.symvers`.
2. Produce the same bundle layout `tools/liveboot/build-kernel.py` produces:
   `Image.gz`, `dtb/<dtb>`, a `modules/lib/modules/<release>/` tree with
   depmod metadata regenerated on the host for that release (`depmod -b`),
   `kernel.config`, `System.map`, and `bundle.json` (schema_version 1,
   release, image/dtb sha256, `modules_install`, `module_files`). Study how
   `build-kernel.py` seals its bundle and reuse its helper functions by
   importing them (add `tools/liveboot` to `sys.path`) rather than copying.
3. Fedora's `vmlinuz` is an EFI zboot image with a zstd payload.
   `prepare-fixture.py` already has a decoder that yields a gzip `Image.gz`;
   import and reuse it.
4. Run the same validations `build-kernel.py` applies to a finished bundle:
   complete gzip stream, arm64 Image magic, release banner present in the
   Image, every module's vermagic equals the release, module tree complete
   against `modules.order`/`modules.dep`. Fail loudly on any mismatch.
5. Write `provenance.json`: each RPM's NEVRA and sha256, the kernel release,
   and the koji build NVR derived from the RPMs.
6. Write `early-modules.txt`: for every module name in
   `force_drivers`/`add_drivers` of `tools/liveboot/profiles/google-sargo-initrd.conf`,
   one line `name present|builtin|absent` using the bundle's `modules.dep`
   and `modules.builtin`. Print a one-line summary of counts.
7. Add `hwe/tools/test-fedora-kernel-bundle.py` in the style of the existing
   `tools/liveboot/test-*.py` scripts, covering at least: zboot decode to a
   valid gzip Image, early-module classification, and bundle.json shape.
   Use small synthetic inputs; do not depend on the real RPMs in the test.
8. Run the tool for real against `out/hwe/rpms` into
   `out/liveboot/candidates/stock-rawhide-73rc3-01`. Then run
   `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 hwe/tools/test-fedora-kernel-bundle.py`
   and the existing `tools/liveboot/test-*.py` suite. Capture full outputs to
   files under `out/hwe/A1/`; do not pipe build or test output through
   `tail`/`grep` when reporting.

## Report

Write `out/hwe/A1/REPORT.md` with: files changed, exact commands run, test
results (pass/fail counts with paths to the full logs), the bundle path and
its `release`, the `early-modules.txt` summary, anything you could not do,
and any assumption you made. Stop after writing the report.
