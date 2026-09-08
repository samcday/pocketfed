# Temporary swipe trial

This bundle contains source-built, unsigned prototype binaries. It is separate
from the stable COPR packages. It enables English (US) whole-word swipes with a
fading trail; release the gesture, then select a candidate to insert it.

Run these commands from the bundle directory as the normal Phosh user:

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

A reboot removes these changes. An image already staged remains staged and will
boot normally. The helper preserves deployment requests, pins, initramfs settings
and the original keyboard trial's saved state. It refuses unknown executable
bytes or an existing hotfix unlock instead of overwriting another experiment.

The bundle must contain `live-swipe.py`, `manifest.json`, and these four files:

- `payload/phosh-osk-stevia`
- `payload/verbisaged`
- `payload/verbisage`
- `payload/mobi.phosh.osk.gschema.xml`

The manifest contains `format: 1`, `architecture: "aarch64"`, and a `files` object
mapping exactly those four basenames to objects containing their `sha256` values.
Target paths and the temporary override contents are fixed in the helper.
`verify` checks this payload on any architecture and does not require phone state.
