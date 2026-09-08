# Actual Stevia / GTK4 Wayland validation

These portable helpers click the real Stevia keyboard on a private 360×720
headless Phoc output. A disposable GTK4 TextView records preedit and committed
text. The helper uses virtual pointer events; it does not inject text or emulate
an input method. Each run has a private session bus and in-memory GSettings.
No live desktop settings or keyboard processes are changed.

Requirements: Python 3 with PyGObject/GTK4, Phoc, grim, dbus-run-session, gdbus,
the patched Stevia executable, a compatible Verbisage daemon and English data.
Build the helper with a C compiler, wayland-devel and pkg-config:

```sh
cd packages/stevia/validation
wayland-scanner client-header wlr-virtual-pointer-unstable-v1.xml virtual-pointer-client.h
wayland-scanner private-code wlr-virtual-pointer-unstable-v1.xml virtual-pointer-protocol.c
cc -O2 -o virtual-pointer virtual-pointer.c virtual-pointer-protocol.c \
  $(pkg-config --cflags --libs wayland-client)
python3 run-wayland.py --output /tmp/stevia-helo-check --case helo
```

The output directory must not exist. Results include JSON, protocol logs and
screenshots for local inspection. Executable and dictionary hashes identify
what ran. These outputs are intentionally not committed here.

| Case | Required behavior |
| --- | --- |
| `literal` | Space commits the typed `hello ` |
| `phrase` | Consecutive words commit `hello world ` |
| `completion` | Select `hello` after typing `hell` |
| `correction` | Select `the` after typing `teh` |
| `helo` | Select the second candidate `hello` after typing `helo` |
| `helo-literal` | Space preserves the typed `helo ` |
| `backspace` | Delete from `hello` to `hell`, then commit |
| `focus` | Changing focus clears preedit without a late commit |
| `unavailable` | A separate missing-dictionary config makes `Complete` fail; literal typing still commits |

Pass `--stevia /path/to/extracted/phosh-osk-stevia` to test an extracted RPM.
`--service-command '["/path/to/verbisaged","--mode","dbus","--config","/path/to/config.toml"]'`
selects a daemon/config; `--dictionary /path/to/en_US.dict` records its data hash.
The helper is compiled for the machine running the test. GTK library overrides
are removed so the installed GTK is used.

`--container-rendering` enables Glycin's documented development override only
in child processes when a nested container cannot provide its sandbox mount.
Leave this option absent for ordinary host/device runs. The test also waits for
Stevia's existing headless animation guard before clicking.

The fixed layout/candidate coordinates make this a functional regression
harness, not a general UI driver or physical-touch benchmark. The adapter's
separate fake-service tests cover delayed replies, cancellation and timeout.
Helpers are GPL-3.0-or-later; the protocol XML retains its MIT header and its
pinned source is recorded in [protocol-provenance.json](protocol-provenance.json).
