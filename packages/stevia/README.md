# Stevia with Verbisage and whole-word swipe

Release `0.57.0-1.3.pocketfed` packages the tested
[Stevia swipe tree](https://github.com/samcday/stevia/tree/codex/swipe-prototype)
at `95db18fa9f90ea63f157f8fb11a2b6ac70971332`. Its three patches apply to the
checksummed Fedora v0.57.0 source. The prepared RPM's 201 source, schema and test
files match the tested tree byte for byte.

The asynchronous Verbisage completer uses ranked `Complete` responses for
prefix and typo suggestions. Whole-word gestures send actual key geometry and
a bounded trace to `RecognizeSwipe`. Release shows the top result as editable
preedit; alternatives remain available. Continuing with a tap or another swipe
accepts that word. Shift and Caps Lock work. Movement begins capture at GTK's
drag threshold; stationary holds retain alternate characters. The trail fades
over 1.5 seconds.

Backspace immediately after selecting a completion restores the preceding
composition and candidates, including swipe alternatives. This requires an
exact acknowledgement of the inserted text/cursor. Focus, cursor, mode and
other input changes invalidate the single undo. Engines that own selection
editing retain control.

Swipe is disabled by the package default. The personal sam-sargo image enables
it and selects Verbisage; shared PocketFed images keep their existing package
allowlists and defaults. The paired service is Verbisage 1.3, with
`verbisage-dbus-recognize-swipe = 1`. The image checks that capability alongside
`stevia-swipe-typing = 1` and `stevia-completion-undo = 1`.

Initial scope remains English-US whole words in eligible normal text fields;
password/PIN and sensitive fields, mixed typed/swipe words and learning are
excluded. This is the tested daily-driver experiment, not a general gesture
accuracy claim. The prior source trial passed all 73 Meson targets, 11 private
host interactions and seven native phone interactions. COPR builds run the
complete Meson suite again from the RPM source. The older `validation.json`
records release 1.2; it is historical.

Source hashes are in `sources.sha256`; source and protocol pins are in
`provenance.json`. The packaged `SWIPE-PROTOTYPE.md` describes behavior and
bounds. The existing `validation/` directory documents isolated Wayland
checks; the v2 interaction harness is also published on PocketFed's
`codex/swipe-prototype-trial` branch.
