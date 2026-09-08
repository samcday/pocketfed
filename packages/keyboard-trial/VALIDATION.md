# Validation scope

These are summaries of checks completed for the existing package inputs.
The formalization changes packaging visibility and documentation, not runtime
source. Main-COPR build results are available on the public package build pages.

| Component | Completed checks |
| --- | --- |
| Stevia 1.2 | Full Fedora `%check`: 72 Meson targets; 14 fake-service adapter scenarios |
| Verbisage 1.2 | 73 Rust tests, two doctests, private D-Bus fixture checks and real English corpus checks |
| Patricia | Curated RPM: four unit tests and five doctests; separate pinned-upstream fixture suite: 77 tests |
| English dictionary | Reproducible preparation and generator output exactly matching the pinned upstream binary hash |
| Drift Type | 59 unit and 16 doc tests with default and all features |
| embed-doc-image | One passing doctest; one intentionally ignored example requiring absent upstream images |

The adapter and real Wayland checks cover ranked `helo` to `hello`, explicit
selection, unchanged literal Space commits and unavailable dictionary handling.
Signed native checks and manual current-word acceptance also passed. This does
not establish general spelling accuracy, physical gesture recognition,
multilingual support, learned words or next-word UI behavior.

Lint is not uniformly warning-free: Stevia retains two provider-package
warnings; Patricia/dictionary preparation uses documented local Source names.
Verbisage retains duplicated license-notice warnings and a duplicated-waste
error because all required vendor notices remain included. Its missing-manpage
warnings were fixed. Per-package `validation.json` files preserve the counts
and local artifact hashes without raw workstation/device records.

Portable reproduction is in the package READMEs, the Verbisage `test-dbus.py`
fixture, [the Stevia Wayland harness](../stevia/validation/README.md), and
[benchmark-complete.py](benchmark-complete.py). Do not infer new signed output
hashes from the previous unsigned local build hashes.
