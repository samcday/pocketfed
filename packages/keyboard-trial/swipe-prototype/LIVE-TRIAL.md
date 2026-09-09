# Temporary swipe trial

This bundle contains source-built, unsigned prototype binaries. It is separate
from the stable COPR packages. It enables English (US) whole-word swipes with a
fading trail. Release shows the best guess as an editable word; keep typing or
select an alternative. Backspace after selecting a candidate restores the prior
word and suggestions.

Keep the complete versioned bundle under `~/pocketfed-keyboard-trial/` so it
survives reboot. Run these commands from its directory as the normal Phosh user:

```sh
python3 live-swipe.py verify
python3 live-swipe.py status
python3 live-swipe.py apply
```

`apply` asks for sudo only to create an ephemeral `/usr` overlay and replace the
three reviewed executables, the OSK schema and its compiled cache. A temporary
schema override enables `swipe-typing`; no saved GSettings/dconf value is written.
The helper checks file hashes, service ownership and the running executables,
and probes both ordinary completion and swipe recognition before reporting success.

A reboot removes the active overlay changes, while a bundle stored under home
remains available for the same `apply` command. An image already staged remains
staged and will boot normally. The helper preserves deployment requests, pins,
initramfs settings and the original keyboard trial's saved state. It accepts
the known deployed 1.1/1.2 binaries, the audited first swipe prototype, or the
identical current payload. Unknown executable bytes and an
existing hotfix unlock are rejected so another experiment is preserved.

The bundle must contain `live-swipe.py`, `manifest.json`, and these four files:

- `payload/phosh-osk-stevia`
- `payload/verbisaged`
- `payload/verbisage`
- `payload/mobi.phosh.osk.gschema.xml`

The manifest contains `format: 1`, `architecture: "aarch64"`, and a `files` object
mapping exactly those four basenames to objects containing their `sha256` values.
Target paths and the temporary override contents are fixed in the helper.
`verify` checks this payload on any architecture and does not require phone state.
