# Google Sargo call audio

This rootfs overlay carries the minimal userspace configuration for voice-call
audio on Sargo. It deliberately contains only the upstream `VoiceCall` UCM;
HiFi/media routing is outside this slice.

The UCM files and symlink are copied without modification from
[`sdm670-mainline/alsa-ucm-conf`](https://gitlab.com/sdm670-mainline/alsa-ucm-conf)
at commit `1e39c9fce12cb521bb53a6422532822b2e4faa10`.
The source archive SHA-256 is
`606ecece34efa340f1c7e0ab3660b507207b59200618bd4f3855172ac4642a20`.
Their BSD-3-Clause license is installed with the files.

`q6voiced.conf` selects Sargo's `VoiceMMode1` PCM at card 0, device 4. The
daemon is transitional: remove q6voiced and this configuration once kernel
codec-to-codec routing supersedes the dedicated voice PCM.
