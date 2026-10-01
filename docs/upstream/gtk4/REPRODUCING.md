# Reproducing the preedit failure

Run the following from this report's directory. A Linux Wayland development
host needs Phoc, a C compiler, GTK 4 development files, Python 3, D-Bus,
libwayland-client, and the chosen GTK build's dependencies. The Python input
method uses `ctypes` and the bundled protocol XML; no third-party Python module
is required. All input is fixed disposable test text.

## Real keyboard check

Compile the small probe:

```sh
cc -Wall -Wextra -Wno-unused-parameter harness/gtk4-preedit.c \
  -o /tmp/gtk4-preedit $(pkg-config --cflags --libs gtk4)
```

In a Phosh/Stevia session, use a text field with word completion enabled
(Stevia completion mode `['hint']`). Focus this probe's text view and type
`hello` followed by a space. The probe requests word completion.

Expected: composition remains visible and commits as `hello `.
Affected GTK: composition appears briefly and is cleared before commitment.
Disabling completion avoids this path because Stevia commits characters directly.

```sh
WAYLAND_DEBUG=client /tmp/gtk4-preedit 2>/tmp/gtk4-preedit.log
```

## Frozen bisect harness

Build the chosen GTK revision without installing it. The original source
builds used host GLib 2.88.3 and private Pango 1.58.2, with these options:

```sh
meson setup build --buildtype=debugoptimized --wrap-mode=nofallback \
  -Dx11-backend=false -Dwayland-backend=true -Dvulkan=disabled \
  -Dmedia-gstreamer=disabled -Dprint-cups=disabled -Dintrospection=disabled \
  -Dbuild-testsuite=false -Dbuild-tests=false -Dbuild-demos=false \
  -Dbuild-examples=false -Ddocumentation=false
meson compile -C build gtk-4
```

Then prepare a disposable harness directory:

```sh
trial_dir=$(mktemp -d)
cp harness/* "$trial_dir/"
cc -Wall -Wextra -Wno-unused-parameter -Werror \
  "$trial_dir/gtk4-preedit.c" -o "$trial_dir/gtk4-preedit" \
  $(pkg-config --cflags --libs gtk4)
dbus-run-session --config-file="$trial_dir/dbus.conf" -- \
  python3 "$trial_dir/run-case.py" \
  --library-dir /absolute/path/to/gtk/build/gtk \
  --dependency-dir /absolute/path/to/dependencies/lib64 \
  --output "$trial_dir/result"
```

Use `/usr/lib64` as the dependency directory when the host libraries suffice,
or as the GTK library directory for an installed GTK. Output must not already
exist. Exit 0 means preserved/committed preedit, 1 means cleared preedit, and
125 means an invalid trial. An invalid trial must not be counted as a bad
revision or silently skipped during a bisect.

The runner uses a private runtime directory and D-Bus configuration without
service activation, Phoc's headless pixman renderer, GTK's Cairo renderer,
`GTK_A11Y=test`, and `GDK_WAYLAND_DISABLE=wp_cursor_shape_manager_v1`. The latter
two settings avoid unrelated accessibility and cursor-shape startup failures
in intermediate revisions. Those failures paused the original bisect; after
adjusting the environment, the same revisions ran valid trials. No source
workaround was used to classify them.

## Seven-scenario validation

Copy `validation/*` instead of `harness/*`, compile its C probe with the same
command, and run:

```sh
python3 "$trial_dir/run-matrix.py" \
  --harness "$trial_dir" \
  --library-dir /absolute/path/to/gtk/build/gtk \
  --dependency-dir /absolute/path/to/dependencies/lib64 \
  --output "$trial_dir/matrix" --label candidate
```

The matrix validates ordinary text, UTF-8 text, punctuation, geometry changes,
explicit reset, logical cursor movement, and focus loss. The action driver
waits 100 ms for focus/setup notifications before sending preedit, preventing
an initial serial race in the pre-populated cursor test. Each scenario's
expected exit is recorded explicitly; all seven must have `passed: true`.

To test the candidate, apply the main patch to GTK 4.23.3/4.23.4; use the
cause-only patch when testing the first bad commit. Rebuild and point the
harness at that build's library. Tests against historical builds are already
recorded; a current-main build and upstream CI remain follow-up work.

## Rebuilding the recorded Fedora package

The packaging directory contains the Fedora-derived spec and source checksums.
Download `gtk-4.23.4.tar.xz` from
[GNOME's source archive](https://download.gnome.org/sources/gtk/4.23/gtk-4.23.4.tar.xz)
to a disposable source directory, verify `packaging/sources.sha256`, and copy
`patches/gtk4-wayland-preserve-preedit-on-layout.patch` into that directory.
Then build an SRPM with `rpmbuild -bs`, setting `_sourcedir` and `_srcrpmdir` to
that directory and defining `dist .fc46` and `fedora 46`. This reproduces the
packaging inputs; it does not claim bit-for-bit reproducible RPM output.
