# Stevia Verbisage trial

This Fedora Stevia rebuild adds an opt-in `verbisage` completion backend.
It requests a ranked list of current-word candidates from the session D-Bus service
provided by Verbisage and reuses Stevia's candidate bar and Wayland preedit/commit
handling. The service selects its own dictionary backend; this client does not
link to Hunspell, Patricia, or Verbisage. Fedora's existing Hunspell backend
remains built and remains the default.

The trial supports `en_US`. It provides completion of the current word and
explicitly selected spelling corrections. It does not add swipe typing,
next-word predictions, dictionary learning, or correction undo.

## Enable and restore

With the patched Stevia, Verbisage, and its English dictionary installed, run
as the Phosh user:

```sh
gsettings set mobi.phosh.osk.Completers default verbisage
```

The running keyboard watches this setting and switches the active completer
immediately for an ordinary language layout such as English (US); no restart
is needed. Layouts with their own explicit input-method configuration retain
that engine, and a terminal/emoji view picks up the new default when returning
to a language layout. Hint-based completion remains the distribution default;
applications such as Chatty request it. To restore the previous default backend:

```sh
gsettings reset mobi.phosh.osk.Completers default
```

If the user had selected a different backend before the trial, restore that
saved value instead of resetting it. The backend also appears as
`Verbisage (experimental)` in the installed completer metadata.

The original typed spelling is always the first candidate. Space and Enter
commit the original text, and Enter still reaches the application as a key.
Only selecting a candidate applies a correction. Queries are debounced by
60 ms and time out after one second. One reply supplies up to five unique
ranked suggestions alongside the original spelling, for six candidates total.
The client keeps the service's order rather than interpreting its score values.
Title case and all-caps input are preserved in the suggestions.
Late replies cannot change a newer composition. Reset, language change, focus
loss, backend change, and destruction invalidate outstanding requests. The
input remains usable if the daemon is missing, stopped, slow, or returns an
error; dictionary failures never discard or automatically commit the preedit.

## Source and packaging

The baseline is Fedora Rawhide Stevia 0.57.0, dist-git commit
`f0581fa27e5b50b302529922baf1c112dde7ff06`. The archive's SHA-512 matches Fedora's
`sources` file. `sources.sha256` pins the same archive for the repository's
packaging workflow, and `provenance.json` records its origin.

The spec retains Fedora's dependencies, build flags, subpackages, desktop
validation, and full headless Mutter test run. Changes are the integration
patch plus a separate ranked-completion follow-up patch, explicit
`1.2.pocketfed` release/changelog, a `dbus-daemon` test dependency, and
`stevia-completer-verbisage = 1` / `stevia-completer-verbisage-ranked = 1`. The optional backend does not make Verbisage
a hard runtime dependency of every Stevia installation.

From the repository root, after downloading the source archive:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
curl --fail --location \
  https://gitlab.gnome.org/World/Phosh/stevia/-/archive/v0.57.0/stevia-v0.57.0.tar.gz \
  --output "$srpm_dir/stevia-v0.57.0.tar.gz"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/stevia/sources.sha256")
cp packages/stevia/stevia-0.57.0-*.patch "$srpm_dir/"
rpmbuild -bs \
  --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
  --define 'dist .fc46' --define 'fedora 46' packages/stevia/stevia.spec
```

Build targets are `fedora-rawhide-aarch64` and `fedora-rawhide-x86_64`.
The runtime image selection is limited to the personal sam-sargo image; shared
PocketFed image allowlists remain unchanged. See [scope](../keyboard-trial/README.md).

## Protocol and tests

The client calls `org.verbisage.Dictionary1` at `/org/verbisage/Dictionary` on
the session bus name `org.verbisage.Dictionary`:

| Method | Input signature | Output signature |
| --- | --- | --- |
| `Complete` | `s u s`: word, maximum results, language | `a(sd)` |

`Complete` is provided by the paired Verbisage 1.2 trial. The client requests
six results, deduplicates them against the literal spelling, and displays at
most five suggestions. It does not fall back to older APIs: a daemon without
`Complete` leaves the literal candidate usable. Input longer than 128 Unicode
characters remains literal without a request.

The patches include `test-completer-verbisage`, which runs 14 cases against a
private fake D-Bus service. These cover ranked order and the total cap, one
complete response, unchanged-result notification suppression, title/all-caps
handling, duplicate/exact-word results, stale replies, reset, language changes,
daemon errors/recovery, timeout, restart, unsupported older services,
Unicode/backspace/Enter/punctuation behavior, destruction in flight, and input
bounds. It exercises the production adapter and needs no display or dictionary.

```sh
meson test -C build test-completer-verbisage --print-errorlogs
```

To exercise that same adapter against a running real Verbisage service and
English dictionary on the caller's session bus:

```sh
GSETTINGS_BACKEND=memory GSETTINGS_SCHEMA_DIR="$PWD/build/data" \
  build/tests/test-completer-verbisage --real-service
```

This real-service mode checks `helo` → `hello` as the first suggestion,
`hell` → `hello`, `teh` → `the`, the six-candidate limit, literal preedit
preservation, and clearing of candidates after reset. It is separate from the
fake-service tests and is not run by `%check`, so package builds do not depend
on a running daemon or a downloaded dictionary.

The 1.2 x86_64 RPM build passed all 72 Meson test targets, including all 14
adapter cases. The production adapter and actual Wayland checks verified
`helo` to `hello`, literal Space behavior, and dictionary-error recovery.
`validation.json` summarizes the checks and local build hashes. See
[the integration harness](validation/README.md) for reproducible checks and
[DOWNSTREAM.md](DOWNSTREAM.md) for the public implementation fork.
