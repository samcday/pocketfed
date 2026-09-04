# Google Sargo call audio

This rootfs overlay carries the minimal userspace configuration for voice-call
audio on Sargo. It deliberately contains only a `Voice Call` UCM;
HiFi/media routing is outside this slice.

The UCM files and symlink are based on
[`sdm670-mainline/alsa-ucm-conf`](https://gitlab.com/sdm670-mainline/alsa-ucm-conf)
at commit `1e39c9fce12cb521bb53a6422532822b2e4faa10`.
The source archive SHA-256 is
`606ecece34efa340f1c7e0ab3660b507207b59200618bd4f3855172ac4642a20`.
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
it with microphone semantics.

`q6voiced.conf` selects Sargo's `VoiceMMode1` PCM at card 0, device 4. The
daemon is transitional: remove q6voiced and this configuration once kernel
codec-to-codec routing supersedes the dedicated voice PCM.
