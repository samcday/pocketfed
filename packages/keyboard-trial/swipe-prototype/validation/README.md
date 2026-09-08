# Private swipe integration checks

This extends the [existing Stevia/GTK4 harness](../../../stevia/validation/README.md)
with a synthetic pointer drag through the real keyboard. Each case starts its
own session bus, headless 360×720 Phoc output and disposable GTK4 text field.
It never inserts text directly into that field, changes live GSettings or
restarts the desktop keyboard. The binaries and dictionary are recorded by
SHA-256. Logs contain only synthetic test text, but local paths and installed
package context should be reviewed before publishing results.

Build `virtual-pointer` using the existing harness instructions. Build the new
`virtual-drag.c` beside it with the same generated `virtual-pointer-client.h`
and `virtual-pointer-protocol.c`:

```sh
cc -O2 -o virtual-drag virtual-drag.c virtual-pointer-protocol.c \
  $(pkg-config --cflags --libs wayland-client)
```

The tools directory must contain both helpers and the existing `gtk4-probe.py`.
Copy the prototype Stevia build's `data/*.xml` schemas to a private schema
directory and add this override before running `glib-compile-schemas` there:

```ini
[mobi.phosh.osk]
swipe-typing=true
completion-mode=['hint']
[mobi.phosh.osk.Completers]
default='verbisage'
```

With the matching prototype binaries and an English dictionary configured for
the daemon, run:

```sh
python3 run-swipe.py --case swipe --output /tmp/swipe-result \
  --stevia /path/to/phosh-osk-stevia --tools-dir /path/to/tools \
  --schema-dir /path/to/private-schemas \
  --service-command '["/path/to/verbisaged","--mode","dbus","--config","/path/to/trial.toml"]' \
  --dictionary /path/to/en_US.dict
```

Use a fresh output directory for each run. `swipe` checks that no crossed-key
letters enter preedit or committed text, measures the trail fading to zero,
then explicitly selects `hello` and checks the exact `hello ` commit.
`swipe-focus` moves focus away during the drag and checks that no text leaks.
`literal` verifies ordinary taps still form preedit and Space commits the raw
word. These are integration checks for a fixed layout and synthetic path,
not an accuracy benchmark or a physical touchscreen test.

Pillow is needed for pixel comparison. On a test device without it, use
`--defer-pixel-check`, copy the result directory to a host with Pillow, then run:

```sh
python3 verify-trail.py /path/to/copied/swipe-result
```

The device result remains `pending-pixel-check` until this succeeds. The host
writes a separate `result-verified.json` with measured decay and hashes of the
original result and four PNGs; it preserves the captured files. A zero exit
from the deferred device run means only that its functional checks passed.

In nested containers only, `--container-rendering` applies the existing
process-local Glycin rendering accommodation. It is absent by default and
must not become a production keyboard setting. Native tests should use the
installed GTK libraries, with no LD_LIBRARY_PATH or LD_PRELOAD override.
