# Keyboard layout trial bundle

Source-only tooling to build a locally reviewed keyboard-trial bundle from the
pinned layout-aware Stevia/Verbisage sources. It produces the three trial
binaries plus the matching OSK GSettings schema, records exact source/build
identities, and refuses architecture mismatches.

This directory deliberately does **not** change PocketFed images, package sets or
deployment defaults, and it does not touch a device. Building and auditing run
wherever the matching toolchain already exists; the ephemeral device trial in
[Ephemeral device trial](#ephemeral-device-trial-user-run-later) is left for a
later user-run session.

- Pins: [`sources.json`](sources.json)
- Recipe: [`trial-bundle.py`](trial-bundle.py) (`build`, `audit`, `selftest`)
- Validation: [`VALIDATION.md`](VALIDATION.md)

## Pinned sources

| Checkout | Commit | Role |
| --- | --- | --- |
| `stevia` | `7a00a8fff38ac60d7998a8cc7ec88c6111d4f304` | C Meson client; `phosh-osk-stevia` and the OSK schema |
| `verbisage` | `d7012120bfcacb22dc55eb9009c28a3afe985aac` | Rust service/CLI; `verbisaged`, `verbisage` |
| `keyboard_layout` | `d60e05ce20b77a84ec4ac3a8c38b1c295dfa38fe` | Shared Rust geometry/layout crate |
| `verbisage/patricia_dict` | `32121e2b5cb8615d408eecc9cd55eeb8d51bd7b7` | Rust Patricia reader, nested submodule |
| `drift-type` | `f0b2cc7ac1f84d479abfa6c8e4028f473a8c50b3` | Private gesture-decoder crate |

Public pull requests:
[stevia#1](https://github.com/samcday/stevia/pull/1),
[verbisage#1](https://github.com/samcday/verbisage/pull/1),
[rs-keyboard-layout#1](https://github.com/samcday/rs-keyboard-layout/pull/1).

Compatibility notes carried in `sources.json`:

- The Stevia commit changes the native test stand-in only, so the runtime C
  source is unchanged from the tested parent
  `8f8b6bdc649b520cfa4210dc9c22e0af7b76039a` (whose own parent is the exporter
  `e688e6a2d48eec1bf26c55e102061cfbac8c025b`). Build output hashes are
  path-dependent and are not expected to match across build directories.
- Verbisage `d701212` is a documentation-only child of the tested
  `34f2a1ca7160812fa8d47565dcc0ddf664c4906b`.
- `drift-type` is private and may only be consumed locally by authorized users.

## Retrieve the exact sources

Clone each repository and check out the pinned commit into the sibling layout
below. `Cargo.toml` path dependencies resolve relative to these positions;
`Cargo.lock` records crate versions but **does not** pin path-dependency
commits, so verify each commit explicitly.

```sh
root=~/pocketfed-keyboard-trial/sources

git clone https://github.com/samcday/stevia.git "$root/stevia"
git clone https://github.com/samcday/verbisage.git "$root/verbisage"
git clone https://github.com/samcday/rs-keyboard-layout.git "$root/keyboard_layout"

git -C "$root/stevia"          checkout 7a00a8fff38ac60d7998a8cc7ec88c6111d4f304
git -C "$root/verbisage"       checkout d7012120bfcacb22dc55eb9009c28a3afe985aac
git -C "$root/keyboard_layout" checkout d60e05ce20b77a84ec4ac3a8c38b1c295dfa38fe

# Patricia is a submodule of verbisage at path patricia_dict:
git -C "$root/verbisage" submodule update --init patricia_dict
git -C "$root/verbisage/patricia_dict" checkout 32121e2b5cb8615d408eecc9cd55eeb8d51bd7b7

# Private Drift Type; authorized local users only:
git clone git@gitlab.com:InsanePrawn/drift-type.git "$root/drift-type"
git -C "$root/drift-type" checkout f0b2cc7ac1f84d479abfa6c8e4028f473a8c50b3
```

The public pins are the heads of the PRs above. If a `checkout` cannot find the
commit after a default clone, fetch the PR head first, for example
`git -C "$root/stevia" fetch origin pull/1/head`.

If an existing checkout is dirty but its `HEAD` still matches the pin, pass
`--export-commits` to `trial-bundle.py build`. It `git archive`s each pinned
commit into a fresh sibling tree, so unrelated working-tree changes are never
built and never reset.

## Build prerequisites

The recipes read these requirements from the local `meson.build`/`Cargo.toml`;
do not reuse stale RPM packaging lists. Install the matching development
packages for the target host (Fedora names shown for convenience).

Client (Meson, `c`):

- `meson`, `ninja`, `gcc`, `pkgconf-pkg-config`, `gettext`, `git`, `python3`
- pkg-config modules: `glib-2.0 >= 2.80`, `gio-2.0`, `gobject-2.0`, `dconf >=
  0.49`, `gmobile >= 0.2.0`, `gnome-desktop-3.0 >= 3.26`,
  `gsettings-desktop-schemas >= 47`, `gtk+-3.0 >= 3.22`, `gtk+-wayland-3.0`,
  `gdk-3.0`, `gdk-wayland-3.0`, `json-glib-1.0`, `libfeedback-0.0`, `libhandy-1
  >= 1.1.90`, `libsystemd` or `libelogind >= 241`, `wayland-client >= 1.14`,
  `wayland-protocols >= 1.12`, `xkbcommon`
- at least one completer backend, e.g. `hunspell` (`presage` also accepted);
  Meson fails with "No usable completer found" otherwise
- `glib-compile-schemas` and `glib-compile-resources` from `glib2` on `PATH`

Service (Cargo, Rust):

- a stable Rust toolchain with edition 2024 support; this bundle was checked
  with `cargo`/`rustc` 1.98.0
- `cc` for the bundled SQLite in `rusqlite`; the remaining crate graph is Rust
- the client and service can be built on a native `x86_64` or `aarch64` host.
  For cross-compilation supply `--meson-cross-file` and `--cargo-target`.

## Produce a bundle

`build` requires new `--output` and build directories and never overwrites an
existing one. Example for a native `x86_64` host:

```sh
python3 tools/keyboard-layout-trial/trial-bundle.py build \
  --sources-root ~/pocketfed-keyboard-trial/sources \
  --build-root ~/pocketfed-keyboard-trial/build \
  --output ~/pocketfed-keyboard-trial/bundle \
  --arch x86_64
```

On a native `aarch64` host (for sam-sargo) set `--arch aarch64`; the produced
binaries are checked against that architecture. This repository has only
validated the `x86_64` path; no `aarch64` compilation or device run has been
performed here.

`build` verifies every pinned checkout commit, compiles Stevia and Verbisage,
stages the artifacts, compiles the schema, self-audits the staging directory and
only then renames it to `--output`.

### Bundle layout

```
bundle/
  bundle-manifest.json
  bin/phosh-osk-stevia
  bin/verbisaged
  bin/verbisage
  share/glib-2.0/schemas/mobi.phosh.osk.gschema.xml
  share/glib-2.0/schemas/mobi.phosh.osk.enums.xml
  share/glib-2.0/schemas/gschemas.compiled
```

`bundle-manifest.json` records the requested architecture, toolchain versions,
the verified source commits and paths, the build options/features, and a
SHA256 + ELF machine for every artifact.

## Audit a bundle

```sh
python3 tools/keyboard-layout-trial/trial-bundle.py audit \
  --bundle ~/pocketfed-keyboard-trial/bundle \
  --arch aarch64 \
  --verify-pins
```

`audit` fails on a missing artifact, any SHA256 mismatch, any ELF machine that
does not match `--arch`, and (with `--verify-pins`) any source commit that does
not match `sources.json`. It does not rebuild or modify the bundle.

## Ephemeral device trial (user-run, later)

This is a plan, not executed or validated here. The bundle is meant to be
applied over a transient writable `/usr` so a reboot discards it, but do not
assume that: confirm the state below and restore backups explicitly. No image,
package or saved keyboard setting is changed. Do not reuse
`swipe-live-2/live-swipe.py`: its allowlisted stable/prototype hashes predate
this work, and this bundle does not ship it.

Preflight (record, do not change):

1. Confirm the bundle architecture matches the device: `uname -m` must equal the
   bundle's manifest `arch`.
2. Snapshot deployment state: `rpm-ostree status` to a file.
3. Record the then-current installed binaries: `readlink -f` and `sha256sum` for
   `/usr/bin/phosh-osk-stevia`, `/usr/bin/verbisaged`, `/usr/bin/verbisage`
   (where present).
4. Record the current global schema inputs and compiled output:
   `/usr/share/glib-2.0/schemas/mobi.phosh.osk.gschema.xml`,
   `/usr/share/glib-2.0/schemas/mobi.phosh.osk.enums.xml` (if present) and
   `/usr/share/glib-2.0/schemas/gschemas.compiled`, with `sha256sum`.
5. Record the current runtime identities: the owning process(es) of the keyboard
   and language service (`pgrep -af`, `readlink -f /proc/<pid>/exe`) and the
   session units that own them (`systemctl --user status`).
6. Record overlay ownership before touching anything:
   `findmnt -no SOURCE,FSTYPE,OPTIONS /usr` (or `mount | grep ' /usr '`). If
   `/usr` is already a writable overlay owned by another experiment, do not run
   `usroverlay` a second time; coordinate with that experiment and reuse its
   overlay only if agreed.
7. Back the files above up to a persistent directory, for example
   `~/pocketfed-keyboard-trial/backup-<timestamp>/`.
8. Dump stored keyboard settings: `gsettings list-recursively mobi.phosh.osk`.
9. Confirm no other live experiment currently owns those paths; coordinate
   before replacing anything.

Apply (transient):

1. If `/usr` is not already a writable overlay, run `sudo rpm-ostree usroverlay`
   and confirm `/usr` is writable. If it already is, reuse it; do not stack a
   second overlay.
2. Install the bundle binaries over the backups with `install -m 0755`.
3. Copy only the schema XMLs from the bundle into the global schema directory:
   `/usr/share/glib-2.0/schemas/mobi.phosh.osk.gschema.xml` and
   `.../mobi.phosh.osk.enums.xml`, then run
   `sudo glib-compile-schemas /usr/share/glib-2.0/schemas`. Do **not** copy the
   bundle's `gschemas.compiled` over the global compiled file: that bundle was
   compiled from this schema alone and does not contain the rest of the system
   schemas. Always recompile the global directory.
4. Restart the affected session keyboard/language units through the user's
   normal session means; read the actual unit names from the installed system
   rather than assuming them. Verify the running processes are the new files by
   comparing `/proc/<pid>/exe` against the bundle.

Exercise: tap completion/correction, the `d`/`o`/`n`/period/`t` swipe and its
alternates, rapid mixed swipes and literals, alternative select and undo,
backspace/Enter, long press, and focus/language/rotation transitions. Record
failures separately from passes. Do not claim recovery of every unacknowledged
edit.

Rollback:

1. Restore the backed-up binaries and schema XMLs and re-run
   `glib-compile-schemas` on the global schema directory, or reboot only if you
   confirmed at preflight that this is a plain transient overlay a reboot will
   discard.
2. Do not assume a reboot is lossless for other experiments: a `/usr` overlay
   may have been opened by another experiment and could carry changes it
   intends to keep. If `/usr` was already unlocked at preflight, restore files
   explicitly and coordinate rather than relying on the reboot.
3. After rollback, re-run the preflight `sha256sum`, `rpm-ostree status` and
   process-identity checks to confirm the originals are back, and re-read the
   `mobi.phosh.osk` settings.

## Boundaries

- No hardware action, package install, image build, COPR/OCI work, container
  start/restart, `rpm-ostree` staging or hidden keyboard-setting change is part
  of this tooling.
- Bundle output belongs in `~/pocketfed-keyboard-trial`, never `/tmp`.
- Only `x86_64` has been built and audited. `aarch64` is required for sam-sargo
  and is supported by the recipe, but its compilation and any device validation
  remain outstanding.
- The private Drift Type source and any internal logs must not be published.
  Public provenance is the pinned public sources and PRs above.
- Reuse the installed dictionary read-only. The bundle contains no dictionary
  data and does not modify system dictionaries; learning, user/system
  interleaving, frequency decay and raw tap capture are out of scope.
