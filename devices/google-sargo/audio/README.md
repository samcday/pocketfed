# Google Sargo call audio

This rootfs overlay carries the minimal userspace configuration for media and
voice-call audio on Sargo. It restores the historical `HiFi` UCM alongside the
canonical `Voice Call` UCM so WirePlumber can enter and leave call mode.

The current UCM files and symlink are based on
[`sdm670-mainline/alsa-ucm-conf`](https://gitlab.com/sdm670-mainline/alsa-ucm-conf)
at commit `1e39c9fce12cb521bb53a6422532822b2e4faa10`.
The source archive SHA-256 is
`606ecece34efa340f1c7e0ab3660b507207b59200618bd4f3855172ac4642a20`.
`HiFi.conf` was restored from its last revision at commit
`3cc4728fc9b3e8fc7183aa2d045b5639ab1a775b`, then forward-ported with the
current DAI names, jack controls, endpoint metadata, and canonical device names.
Their BSD-3-Clause license is installed with the files.

The upstream Sargo file combines the top earpiece and bottom loudspeaker into
one plural `Speakers` device. PipeWire consequently types it as an unknown
output and cannot expose the two phone routes separately. The PocketFed copy
splits those proven amplifier controls into singular `Earpiece` and `Speaker`
devices. Its priorities prefer a connected wired headset, then the earpiece,
and leave the loudspeaker as an explicit choice. This retains the upstream
PCM, mixer, topology, and ACDB selections.

The use-case name is also normalized from the upstream `VoiceCall` spelling to
ALSA's canonical `Voice Call`. WirePlumber's ModemManager hook matches that
canonical name when it automatically selects a call profile. The built-in
microphone likewise uses ALSA's canonical `Mic` device name so PipeWire exports
it with microphone semantics. `Headset` and the combined HiFi `Speaker` are
also canonical UCM device names. Headphones have a slightly higher priority
than the earpiece so jack insertion wins without relying on profile enumeration
order. The `Headphones` output follows `Headphone Jack`, while the `Headset`
input follows the kernel's distinct `Mic Jack`; plain headphones therefore keep
the built-in microphone.

The old HiFi profile was removed upstream only because callaudiod could not
reliably switch away from it. WirePlumber 0.5.11 and newer track ModemManager
call state and select a profile whose name starts with `Voice Call`; when the
call ends, the normal stored/best-profile policy selects `HiFi` again.

`q6voiced.conf` selects Sargo's `VoiceMMode1` PCM at card 0, device 4. The
daemon is transitional: remove q6voiced and this configuration once kernel
codec-to-codec routing supersedes the dedicated voice PCM.
