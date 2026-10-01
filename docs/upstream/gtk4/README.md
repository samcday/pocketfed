# GTK Wayland caret updates cancel keyboard composition

With Stevia word completion enabled, unfinished words briefly appear and then
disappear in GTK 4 text views, including Chatty's composer. A source bisect
identified a GTK Wayland change that reports caret geometry movement as an
external text change. A candidate correction preserves composition in the
recorded source, package, and real-phone tests below.

This is a downstream investigation and candidate fix. It is not an upstream
acceptance record or a claim that the full GTK test suite passed. The work used
LLM assistance for investigation, harnesses, patching, and documentation. The
phone owner independently confirmed the visible before/after behavior.

## Regression and cause

The first bad commit is
[`1d83c7a953209c27a38e92a13fb420493f96669b`](https://gitlab.gnome.org/GNOME/gtk/-/commit/1d83c7a953209c27a38e92a13fb420493f96669b),
“gtk/imwayland: Make text-input caret location animatable”, merged April 4,
2026 in [MR 6922](https://gitlab.gnome.org/GNOME/gtk/-/merge_requests/6922).
The immediate parent
[`87d0eec0d31b2da2c23905b33487aa8eac6a31f7`](https://gitlab.gnome.org/GNOME/gtk/-/commit/87d0eec0d31b2da2c23905b33487aa8eac6a31f7)
is good. Both sides were rebuilt and tested again after the bisect; no commits
were skipped. The [bisect log](evidence/bisect.log) and
[trial records](evidence/outcomes.jsonl) retain revision IDs, classifications,
and mapped-library hashes.

The introducing change calls `notify_im_change(...OTHER)` when the caret
rectangle changes. Rendering preedit moves that rectangle without changing
surrounding text or its logical cursor. The resulting
`text_input_v3.set_text_change_cause(OTHER)` causes Stevia to discard composition.
Later commit
[`bf874024b901`](https://gitlab.gnome.org/GNOME/gtk/-/commit/bf874024b901caddd948f9124a2f663ef517dd7d)
moves the notification into `after_layout_cb()` and retains the same cause.

The [candidate patch](patches/gtk4-wayland-preserve-preedit-on-layout.patch)
keeps geometry notifications and uses `INPUT_METHOD` for them. Explicit
`gtk_im_context_wayland_reset()` still reports `OTHER`. A separate
[cause-only patch](patches/first-bad-cause-fix.diff) fixes the first bad revision.

## Recorded validation

| Tested code or package | Result |
| --- | --- |
| Source GTK 4.22.4 | Preedit preserved and committed |
| Source GTK 4.23.1 and 4.23.3 | Preedit cleared; empty buffer |
| Immediate parent `87d0eec0d31b` | Preserved; repeat confirmed |
| First bad `1d83c7a95320` | Cleared; repeat confirmed |
| First bad plus cause-only patch | Preserved |
| Source GTK 4.23.3 plus candidate patch | Preserved; seven-scenario matrix passed |
| Patched GTK 4.23.4 COPR RPM, x86-64 | Seven-scenario matrix passed |
| Same COPR build, aarch64 on Sargo | Seven-scenario matrix passed |
| Installed unpatched GTK 4.23.3 on Sargo | Ordinary-preedit control still failed |
| Real Chatty/Stevia session after booting patched RPM | Phone owner confirmed working with completion enabled |

The [source baseline matrix](evidence/validation-host-stable-summary.json),
[patched source matrix](evidence/validation-fixed-stable-summary.json),
[x86-64 RPM matrix](evidence/rpm-x86_64.json),
[aarch64 RPM matrix](evidence/rpm-aarch64.json), and
[unpatched device control](evidence/device-unpatched-control.json) cover:

- `hello`, `café`, and `hello!` followed by space;
- widget movement during preedit;
- explicit IM reset and logical cursor movement, which must clear composition;
- focus loss, which must deactivate the input method and clear preedit.

The reset/cursor cases deliberately have classifier `bad` and exit 1: that is
the shared classifier's name for cleared composition, which those scenarios
expect. Their matrix `passed` field is true.

The automated harness uses private headless Phoc sessions, a disposable C
`GtkTextView`, and a synthetic input method. It sends fixed test text, clears
preedit on `OTHER` like the observed Stevia behavior, and commits after 600 ms
if composition survives. Each valid trial checks received preedit, protocol
state, actual buffer content, the mapped GTK library, its version and hash.
It does not exercise Hunspell, a touchscreen, or the whole keyboard stack.
The real-phone confirmation is separate: on September 6, with Stevia's
completion mode `['hint']`, the user reproduced the failure immediately before
reboot and confirmed that Chatty worked after the patched GTK deployment booted.

Source testing used Fedora 44 x86-64, Phoc 0.56.0-2.fc44, GLib 2.88.3,
Pango 1.58.2-1.fc45, Wayland 1.25.0 and wayland-protocols 1.49. Rendering used
Phoc pixman and GTK Cairo. The original phone failure used GTK
4.23.3-1.fc45.aarch64, Phoc 0.57.0-2.fc46, Stevia 0.57.0-1.fc46, and
Chatty 0.8.9-10.fc45. [Reproducer instructions](REPRODUCING.md) include the
build options and workarounds for unrelated intermediate-revision startup
failures.

## Package and upstream status

[COPR build 10954389](https://copr.fedorainfracloud.org/coprs/build/10954389)
produced `gtk4-4.23.4-1.1.pocketfed.fc46` for Rawhide aarch64 and x86-64.
Both builds succeeded and downloaded runtime RPM signatures were verified.
The [packaging inputs](packaging/) identify Fedora dist-git revision
`5f64a17f802215eb67573290fb9066aa662a460e`, source checksums, RPM hashes and
build URLs. The package retains Fedora's `%check`, which validates AppStream
and desktop files and disables the full GTK test suite. The targeted preedit
matrix ran separately against the resulting RPMs.

On September 8, 2026, GTK main was checked at
[`539d28f33b6d285a784c220e6c53ec499d75c078`](https://gitlab.gnome.org/GNOME/gtk/-/commit/539d28f33b6d285a784c220e6c53ec499d75c078).
The [relevant callback](https://gitlab.gnome.org/GNOME/gtk/-/blob/539d28f33b6d285a784c220e6c53ec499d75c078/gtk/gtkimcontextwayland.c#L623)
still reports `OTHER`; the candidate patch applies with no fuzz. That current
revision has not been rebuilt or run with this harness. Public GTK API searches
for issues containing `preedit` or `Stevia` and merge requests containing
`preedit` did not identify this cancellation regression. That limited search
is not proof that no duplicate exists. [Follow-up notes](FOLLOW-UP.md) record
the contribution policy and remaining upstream/Fedora steps.

## Evidence provenance

The [publication manifest](evidence/publication-manifest.json) identifies the
selected local source files and their original/published hashes. Only machine
path prefixes in test JSON were replaced by explicit placeholders; test
observations and library hashes are retained. No personal text, full session
journal, account tokens, or phone deployment details are included.

The input-method protocol XML came from Stevia v0.57.0 and retains its original
MIT license/copyright notice. The patch modifies GTK's LGPL-2.1-or-later source;
upstream source licensing continues to apply. The C/Python harness was created
for this investigation with LLM assistance. Standalone harness files currently have no explicit license grant; confirm
their licensing as part of the upstream handoff.
