# Sargo fingerprint firmware staging

This is a build component for device-local firmware staging in the fingerprint
trial. It contains no proprietary firmware. The first inspection on
11 September 2026 read stock files in phone memory and returned only lengths,
hashes, and selected ELF structure. That inspection performed no staging or
secure application operation. Subsequent controlled trials staged the firmware,
loaded the applications, and accepted a real sensor touch; the current results
and outstanding authentication failure are in
[live-trial-20260911.md](live-trial-20260911.md).

## What exists

The firmware source is `/dev/mapper/vendor_b`, an ext4 mapping containing vendor
build `google/sargo/sargo:12/SP2A.220505.008/8782922:user/release-keys`. At the
first inspection the mapping was writable at the block layer (`RO=0`, `dmsetup`
attributes `L--w`); inspection used `debugfs` without `-w`. After the trial's
slot switch, the exact vendor extent was recreated as a read-only mapping.
That mapping is transient and does not survive reboot. Source extraction always
opens it read-only and refuses a concurrently writable mount.

Blob-wrangler's current library unmounts its temporary vendor view after
extraction. There is no mounted `/var/lib/blob-wrangler/mounts/vendor` left for
a later service to copy from. The firmware search location
`/usr/lib/firmware/updates` is already linked to `/var/lib/firmware-updates`.

The [manifest](firmware-manifest.json) records all 16 required raw files:

| Image | Metadata | Original split segments |
| --- | ---: | --- |
| `fpctzappfingerprint` | 7208 bytes | `b00` through `b07` |
| `cmnlib64` | 7032 bytes | `b00` through `b05` |

Both metadata files are little-endian AArch64 ELF64. Every segment length
matches its program header. Each original MDT equals the original `b00`
header segment followed by the original `b01` signature/hash segment. The
extractor copies those bytes exactly; it does not rebuild an ELF, strip a
signature, or substitute the vendor's assembled `.mbn`. Hash checks identify
the inspected files; they are not an independent cryptographic signature check.

The adapted [kernel loader](../../../packages/kernel-fingerprint/0002-tee-qseecom-support-Sargo-ELF64-images-and-harden-se.patch)
requests `<name>.mdt` and `<name>.bNN` using flat firmware names. Firmware is
requested by a privileged application/common-library load operation, rather
than by merely staging files. `cmnlib64` uses the dedicated common-library
load operation and stays resident for that boot after a successful load.

## Extraction and ordering

[extract-firmware.py](extract-firmware.py) has three explicit modes:

- `--inspect` performs read-only source inspection and emits metadata only.
- `--extract` checks the installed manifest, validates the complete source in
  memory, and stages a complete private bundle under
  `/var/lib/firmware-updates/.sargo-fingerprint/<bundle-hash>/`. Root-owned
  mode-0600 files retain the exact original bytes. Flat firmware names are
  symlinks into that bundle. Existing unrelated firmware names, unexpected
  symlinks, a changed bundle, a writable vendor mount, or different vendor
  bytes fail the service. The source mapping is never created or modified.
- `--ensure` first verifies a previously staged private bundle against all
  pinned lengths, hashes, and ELF structure. Its directories must be real,
  root-owned and not writable by group or others; files must be regular,
  root-owned, mode 0600, and have one link. A valid bundle works without vendor
  access and can restore missing flat symlinks. An absent bundle uses the same
  source extraction as `--extract`; a present but unsafe or damaged bundle fails
  without falling back to the source or overwriting it.

The explicit firmware source is **vendor_b**, independent of the Linux
deployment's A/B boot slot. This trial pins one verified Android firmware
source. It must not silently select vendor_a when vendor_b is absent. Changing
the Android source build requires fresh inspection and a reviewed manifest.

The [static staging unit](pocketfed-fingerprint-firmware.service) requires
successful `blob-wrangler.service` completion before ensuring fingerprint
firmware is available. The updated source uses `--ensure` and makes the vendor
read-only path optional; the device policy grants only read access to vendor_b.
First extraction still requires the mapping to exist. Subsequent boots can
reuse the verified persistent bundle without creating the mapping. This unit
neither opens TEE devices nor loads modules or applications. The new filenames
are absent from blob-wrangler's status list, so its stale-file cleanup does not
own them.

The coordinated dependency chain is:

```text
blob-wrangler.service
  → pocketfed-fingerprint-firmware.service
  → qsee-shared-loader@cmnlib64.service ← qsee-supplicant.service
  → qsee-app-loader@fpctzappfingerprint.service
  → fprintd.service
```

The common-library and FPC application ordering drop-ins are in this directory.
The generic supplicant/loader units belong to the QSEE userspace package.
The fprintd dependencies and device access drop-in belong to the optional
`libfprint-fpc-qsee` subpackage. A successful oneshot is required before the
next loader proceeds. The chain fails if neither a valid cached bundle nor a
complete verified source is available.

[Containerfile.firmware](Containerfile.firmware) installs only the extraction
script, manifest, static unit, ordering drop-ins, and runtime dependencies.
It does not enable or start anything and does not copy firmware into the image.
The main image recipe is intentionally not changed by this component.

**Static does not mean inactive:** stock fprintd D-Bus activation can pull in
the entire dependency chain. The first controlled trial must retain an
explicit fprintd activation gate, and leave the Phosh fingerprint socket
disabled until the planned authentication test. The outer candidate recipe
owns that gate; simply omitting `systemctl enable` on loader units is
insufficient. Keep all QSEE clients stopped during extraction or firmware
changes. Once an application/library is resident, changing files does not
replace it; the controlled reboot boundary remains relevant.

## Long-term blob-wrangler integration

At inspected commit `506ef66df99ebf291e67954af184b626cab9544d`, blob-wrangler's
[`FwFile` and extraction implementation](https://github.com/samcday/blob-wrangler/blob/506ef66df99ebf291e67954af184b626cab9544d/src/firmware.rs)
has only `name` and `rename` fields. A source name ending in `.mdt` always
enters `squash_firmware()` and the destination extension becomes `.mbn`.
Renaming the destination cannot preserve a raw MDT. Adding an unsupported
configuration field would not implement this behavior.

The maintainable upstream change is an explicit per-file extraction mode,
defaulting to today's MDT assembly, with a raw-copy mode that reuses the
existing atomic copy path. Sargo would list raw MDT plus its original split
segments with an empty destination prefix. Missing segments must remain a
failure for consumers that require a complete image. That should be covered
by raw-MDT/signature retention, default assembly compatibility, and missing
segment tests in blob-wrangler. No blob-wrangler source or configuration was
changed here; the narrowly pinned mount-free reader supplies the trial first.

## Checks and limits

`python3 test-extract-firmware.py` passed nine synthetic tests: original
header/signature preservation and truncated segments; wrong hashes;
idempotent installation and recovery from missing links; existing-file and
modified-bundle refusal; preservation of unexpected symlinks; cache reuse with
source access disabled; first-extraction fallback; corrupt-cache refusal without
fallback; and unsafe cache ownership, modes, hardlinks, and symlinks. Fixtures
are generated synthetic bytes in temporary directories. No stock firmware is
used in tests.

`systemd-analyze verify --man=no --generators=no --recursive-errors=no
pocketfed-fingerprint-firmware.service` passed locally for the updated unit.
A read-only on-phone check imported the cache validator, disabled its source
inspection function, and verified all 16 cached files (1,166,860 bytes) against
the installed manifest. It did not call installation, repair symlinks, or change
services. The cache-aware script and unit remain source changes: the installed
unit still uses `--extract`. Installation and a reboot with the vendor mapping
absent remain necessary acceptance checks. Historical image manifests continue
to describe their original inputs and have not been rewritten to imply these
changes were installed. Staging success alone establishes no biometric result.
