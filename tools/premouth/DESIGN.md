# Premouth experiment

Premouth preserves the firmware image inherited on Sargo and dissolves it from
bottom to top into black before yielding to Plymouth. It is an experimental
native Rust crate with a five-second default duration that Plymouth may preempt.
This document records its design; implementation, measured hardware status and
promotion packaging notes are maintained in [README.md](README.md).

## Scope and first gate

Capture, animation and display ownership stay separate. There is no WASM runtime,
plugin interface, theme branding or global service. Packaging installs an
executable and an opt-in dracut module; the base image and Sargo device policy
select it, and installed acceptance remains pending.

The first gate is an authentic image capture, before any modeset. A fixture image
can exercise the animation, but cannot establish recovery of ABL's image.

The cached Sargo `.11` kernel and DTB describe a simple-framebuffer through a
`memory-region` phandle to a 36 MiB no-map reservation at `0x9c000000`. The visible
image is 1080 by 2220 pixels, stride 4320, format `a8r8g8b8`: 9,590,400 bytes. Parse
and validate these properties at runtime instead of treating those numbers as a
license to map arbitrary physical addresses. Do not read spare reservation space.

The exact `.11` source inspected is commit
`132283913205a1db1d57fc3e563eea8224f5b79a`, matching the retained fingerprint build
manifest. In that source, SimpleDRM's memory-region path uses `devm_memremap`
without claiming a busy I/O resource. ARM64 describes the no-map region as
reserved memory without the System RAM flag. This suggests strict `/dev/mem`
may permit a read-only mapping. The subsequent capture-only hardware gate
confirmed this path and recovered a visually intact Google splash.

Use read-only `mmap`, not ordinary `read`/`pread`: no-map memory lacks the direct
kernel mapping used by the read path. ARM64 maps it as Device-nGnRnE, so copy with
aligned volatile 32-bit loads into normal memory. Do not use an optimized memcpy
that could emit invalid unaligned or SIMD accesses to Device memory.

A capture-only probe must not open DRM: even an open followed by last-close can
restore fbdev and change the display. Save the visible bytes, DT geometry, boot
ID, monotonic copy timestamps and relevant policy/error diagnostics for host
inspection. `/dev/fb0` and DRM GETFB expose Linux buffers, not ABL's original
physical image. If capture fails or returns already damaged pixels, retain that
evidence and discuss kernel/ABLX scope before adding an interface there.

## Rendering and ownership

After capture is validated, populate an entire SimpleDRM dumb buffer before the
first modeset. Respect format and pitch. A narrow advancing band uses stable
spatial thresholds to erase pixels once; damage must cover all changes since the
last successful update, including skipped animation ticks.

The raw `a8r8g8b8` capture has ARGB byte semantics. Hardware iteration showed that
the kernel's SimpleDRM plane advertises XRGB8888, and ADDFB2 rejects ARGB8888.
Keep the captured bytes and metadata unchanged, but register the RGB-compatible
XRGB8888 scanout format. The kernel forces alpha opaque when copying into the
firmware framebuffer; initial visual continuity is the acceptance criterion,
not byte-identical physical alpha. Erase to opaque black (`0xff000000`).
The drm 0.14.1 crate's `destroy_framebuffer()` calls RMFB; it is not a suitable
normal-handoff cleanup helper. CLOSEFB requires an explicit UAPI wrapper in that
crate version and cleanup must track whether the framebuffer is on scanout.

Use monotonic elapsed time and absolute frame deadlines. Aim for 60 updates per
second where practical, measuring copy costs, CPU time and ioctl/frame pacing.
SimpleDRM has synthetic completion, so successful 60 Hz updates do not establish
tear-free presentation. Plymouth may preempt the five-second window.

DRM has no weak-master notification mechanism. A bounded `--yield` client in
Plymouth's startup path requests a cooperative handoff. The daemon finishes black,
stops drawing, calls `DRM_IOCTL_MODE_CLOSEFB`, drops master, then acknowledges.
Unlike RMFB, CLOSEFB preserves active scanout. Keep a passive same-device FD until
GETCRTC reports replacement of that framebuffer or the device disappears; this
guards against last-close restoring fbdev before Plymouth opens its FD. Bound the
fallback lifetime. Do not disable the CRTC or restore VT text in normal cleanup.

Probe CLOSEFB support before the first modeset: in the inspected kernel, a zero
framebuffer ID and zero padding return ENOENT from the implemented ioctl. Do not
mistake an arbitrary ioctl failure for support. Natural animation completion must
use the same release-to-passive path as an early yield. GETCRTC replacement proves
only that our framebuffer is no longer selected, not that Plymouth presented a
frame or that the greeter works; those need separate observations.

Retain the original DRM open file after dropping master; do not reopen the card
to create the passive guard. A fresh open can automatically become master again.
Select SimpleDRM by sysfs identity before opening primary nodes, rather than
probing unrelated cards through open/close. The handoff responder remains
idempotent after natural completion. Record disabled scanout, device removal and
query failures separately from replacement. A failed CLOSEFB must not fall
straight through ordinary active-framebuffer destruction; retain ownership until
replacement/removal or an explicitly reported bounded failure fallback.

This FD guard does not suppress independent VT/fbcon output. Use UART-only console
arguments for trials and account explicitly for any KD_GRAPHICS ownership.

## Earliest systemd integration

An opt-in initrd unit needs `DefaultDependencies=no`, no global udev settle or
native graphics dependency, and a short startup handshake before broad coldplug.
`Type=notify` can order successful capture/initial scanout before those consumers
without waiting for the whole animation. `Type=simple` with `Before=` only orders
process launch and leaves a capture race. Missing hardware and startup failure
must permit boot to continue. Preserve the handoff guard across initrd isolation;
do not use `systemctl stop` as the Plymouth handoff.

`IgnoreOnIsolate=yes` is not sufficient by itself: systemd also broadcasts SIGTERM
to remaining initrd processes during switch-root. The daemon's bounded signal
handling must preserve the passive guard through that event, or integration must
establish a suitable explicit survival policy. Do not turn this short-lived
animation helper into an indefinitely protected service.

The packaged unit follows this shape: it is initrd-only, uses `Type=notify`,
starts at most once per boot, and keeps the same bounded signal and passive-guard
behavior. `rd.premouth=0` disables it for one boot. Nothing in the unit waits for
the animation to finish, so Plymouth may preempt it.

## Acceptance criteria

Measured progress against these criteria is recorded in [README.md](README.md).
The final watched run confirmed visual continuity through Plymouth to the
greeter; the evidence distinguishes this human observation from submitted update
counters and does not establish installed acceptance.

- Authentic captured ABL image, visually inspected before drawing.
- Early systemd-initrd startup timestamp and ordering against coldplug/Plymouth.
- Initial image reproduced without an observed visual jump.
- Bottom-up monotonic dissolve ending fully black at the configured duration.
- Measured pacing, CPU time, submitted damage and copied bytes.
- Natural completion and early Plymouth takeover, with no accidental CRTC disable
  or fbdev restoration.
- Missing-device/error paths that let boot continue.

Host tests cannot establish image survival, visual continuity or hardware timing.
