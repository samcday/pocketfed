# Premouth

Experimental, narrowly scoped capture-and-dissolve helper for the Sargo
(sdm670-google-sargo) ABL framebuffer. It reads the firmware image that the
bootloader left in the DT-described `simple-framebuffer` reservation, reproduces
it through SimpleDRM, then dissolves it bottom-up to opaque black before
cooperatively yielding DRM ownership to Plymouth.

This is an experimental prototype. Its test-sargo USB-root trials passed
read-only capture, the dissolve, cooperative handoff and watched boots to Phrog.
Promotion work prepares package and base-image inclusion plus Sargo activation;
installed acceptance on a real deployment is still pending.

## Intended behavior

- **Authentic capture first.** Geometry, stride and format come from
  `/chosen/framebuffer@9c000000` in the live device tree. The `memory-region`
  phandle is resolved in `reserved-memory`; only the validated visible span is
  mapped read-only through `/dev/mem` and copied with aligned volatile 32-bit
  loads into normal memory. Only `no-map` reservations with one `reg` tuple,
  identity `ranges`, reserved-memory cell widths of 1 or 2 and exactly one
  phandle are accepted, and the mapping plan places the visible span at a
  checked page delta. `/dev/fb0` and DRM buffers are not used as capture
  sources.
- **No silent substitution.** If live capture fails, `run` does not modeset and
  does not draw a synthetic image. `--fixture FILE.ppm` is available for host
  animation tests and is reported loudly as a fixture.
- **Capture-only probe never opens DRM.** `premouth capture` writes
  `frame.raw` (exact DT span bytes), `frame.ppm` (derived, for visual
  inspection) and `provenance.txt` (boot ID, DT data, monotonic copy timestamps,
  policy diagnostics) before any display code could run.
- **Separate capture and scanout formats.** Raw `a8r8g8b8` capture retains its
  original alpha bytes. This kernel's SimpleDRM advertises XRGB8888, so the
  dumb buffer uses XRGB scanout with the same RGB byte positions. The kernel
  forces opaque alpha when copying to firmware memory. Visual continuity must
  be checked; physical alpha bytes are not reproduced exactly.
- **Deterministic bottom-up dissolve.** Each pixel has a stable spatial
  threshold derived from its position; progress advances with monotonic elapsed
  time. A narrow band softens the erase front, pixels are written black at most
  once, and no random shimmer is possible.
- **Damage discipline.** Only full-width row-run `DIRTYFB` clips are submitted,
  and every change since the last successful update is re-submitted after any
  failure. At the endpoint every visible pixel is `0xff000000` (opaque black)
  and pitch padding is left untouched.
- **Cooperative handoff.** A root-only Unix socket
  (`/run/premouth/handoff.sock` by default) accepts `premouth --yield`. The
  daemon finishes black, calls `DRM_IOCTL_MODE_CLOSEFB` (which preserves active
  scanout, unlike RMFB), drops master, acknowledges, and keeps one passive FD
  open until `GETCRTC` reports a replacement framebuffer, disabled scanout or
  device removal. Natural completion uses the same release path.

## Host-only evidence

On 2026-09-13, all 66 native tests passed with Rust 1.96.0, including a regression
for Sargo's page-rounded DRM mapping. A static ARM64 musl build also succeeded;
that build is a historical trial artifact, not the RPM payload. A 1080×2220 white
fixture reached exact black in 300 simulated steps. These are host checks, not
phone measurements.

These checks run on a development host without a device. After
`cargo build --release`, host commands use `target/release/premouth`; installed
commands use `/usr/libexec/premouth`, which is not on `PATH`.

- `cargo test` covers damage coverage, irregular/skipped timestamps,
  bottom-to-top direction, monotonic erase state, exact black endpoint, pitch
  padding, PPM fixture parsing, ioctl encodings, mapping-plan arithmetic,
  reserved-memory parsing against synthetic device trees, synthetic sysfs card
  enumeration, and handoff protocol round-trips/split requests/timeouts.
- `target/release/premouth preview --fixture frame.ppm --out DIR` runs the
  animation against an in-memory fixture and writes `preview-initial.ppm` /
  `preview-final.ppm`.
- `target/release/premouth --help`, `target/release/premouth --version`.

Host tests cannot establish image survival, visual continuity, early-initrd
ordering or display-handoff behavior.

## Hardware status

Authentic capture passed first, recovering the intact Google splash. The user
then confirmed that the dissolve appeared and looked good on
`premouth-dissolve-20260913-03`: 301 submitted updates over 5.001 seconds, no
skipped ticks or failed updates, 51 MB submitted damage and 566 ms display-phase
CPU time. Final black, CLOSEFB, master release and passive-guard exit on
Plymouth's framebuffer replacement all passed. Native MSM initialized and the
USB-root/systemd reporter found no failed units. Earlier startup failures also
allowed boot to continue to Plymouth and the Phrog splash.

The zero-delay early-preemption trial also passed: about seven animation
updates over 111 ms, followed by a successful final-black flush, ownership
release and guard exit on replacement. Plymouth started at kernel T+7.950s and
Phrog was running by T+59.620s. A final watched run,
`premouth-visual-20260913-01`, used a six-second artificial Plymouth delay
solely to let the full dissolve finish naturally, and confirmed the complete
Google → dissolve → Plymouth → Phrog/login sequence. The user reported "LGTM!"
when asked about flashes, corruption, console text or a missing login screen.
That run repeated 301 successful updates over 5.001 seconds, used 556 ms
display-phase CPU and exited its guard on framebuffer replacement. These were
test-sargo USB-root trials with a watched UART console; they do not establish
production ordering, installed acceptance, tear-free/vblank presentation or a
five-second production animation.

## Build and test

```
cd tools/premouth
cargo build --release
cargo test
```

A `Cargo.lock` is present for this slice and resolves `drm 0.14.1` plus its
transitive dependencies from the local cargo cache. Keep it updated with any
dependency change. Native Cargo builds and tests remain the development path.

Packaging builds the crate natively on Fedora and installs the executable at
`/usr/libexec/premouth`. The RPM payload is a dynamically linked ELF; dracut
copies its library closure into the initrd. Do not substitute the static musl
trial build for the package payload:

```
CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=rust-lld \
  cargo build --offline --locked --release --target aarch64-unknown-linux-musl
```

That static command is an optional historical trial build retained for the old
USB-root experiments; the RPM does not build or ship it.

## Operator commands

Installed commands live at `/usr/libexec/premouth` and are not on `PATH`; run
them by absolute path. Host commands after `cargo build --release` use
`target/release/premouth`.

```
# read-only probe; never opens DRM
/usr/libexec/premouth capture --out /run/premouth/capture

# host animation preview from an explicit fixture
target/release/premouth preview --fixture frame.ppm --out /tmp/premouth-preview

# live trial (UART console; see console assumptions below)
/usr/libexec/premouth run --duration 5 --capture-out /run/premouth/capture --stats /run/premouth/stats.txt

# ask a running daemon to release the display
/usr/libexec/premouth --yield --timeout 1
```

The yield client uses a single absolute deadline that covers nonblocking
connect, write and read, caps the response size, and defaults to a 1 s bound.
The server buffers split requests until a newline arrives and refuses to unlink
a live daemon's socket on a second startup.

The yield client exit codes are: `0` clean release (or cancellation before
modeset), `3` release with reported black-flush/CLOSEFB failure, `4` another
request is pending, `1` transport/error.

Measured counters and a summary are written to `/run/premouth/stats.txt` when
`--stats` points there. `rd.premouth=0` on the kernel command line disables
Premouth for one boot without changing the installed package or device policy.

## Package and initrd integration

The RPM installs the executable at `/usr/libexec/premouth` and the opt-in
dracut module at `/usr/lib/dracut/modules.d/90premouth`. This change adds the
package to the base image so device policies can select it; the package alone
does not enable the module globally, rebuild an initramfs, preload native
graphics, or install a global service. Initially only the Sargo device policy
selects it with `add_dracutmodules+=" premouth "`. The packaged unit is
initrd-only. Production integration uses ordinary dracut and systemd; no kboop
adapter or artificial Plymouth delay is part of it. Plymouth may preempt the
animation, and the unit does not force boot to wait five seconds.

Unit behavior worth knowing:

- `DefaultDependencies=no`, ordered after `systemd-remount-fs.service` and before broad
  coldplug/Plymouth; `IgnoreOnIsolate=yes`.
- On successful startup, `Type=notify` READY follows authentic capture and the
  first valid scanout. The unit does **not** wait for the five-second animation.
- A terminal `run` error sends READY once before returning, so systemd does not
  report a protocol failure. `SuccessExitStatus=1` tolerates optional runtime
  setup or capture failures; CLI error `2` and release error `3` remain failures.
- Missing devices and startup failures let boot continue. Startup stays bounded
  by `TimeoutStartSec`, and the passive guard stays bounded by `--guard-timeout`.
- systemd still broadcasts SIGTERM during switch-root. The daemon's TERM handler
  performs the same release and then continues the bounded passive guard; it is
  not made unkillable indefinitely.
- `RemainAfterExit` plus a one-start limit keep the unit single-shot per boot,
  preventing later initrd transactions from recapturing the screen or competing
  with Plymouth.

## Console and scope assumptions

- UART is a diagnostic and trial aid, not a mandatory installed runtime
  prerequisite. A quiet installed boot should avoid console redraws. The
  passive DRM FD prevents last-close fbdev restoration, but does not suppress
  independent VT/fbcon writes.
- SimpleDRM copies damage clips synchronously into the firmware region and
  reports synthetic completion. A successful 60 Hz update loop does **not**
  prove vblank-synchronized or tear-free scanout.
- `GETCRTC` replacement proves only that Premouth's framebuffer is no longer
  selected, not that Plymouth presented a frame.
- The passive guard is bounded (`--guard-timeout`, default 20 s). If neither
  replacement nor removal arrives, the process exits and reports the timeout as
  an explicit fallback.
- The RAM-root experiment, device-side block caching and kernel/ABLX changes are
  out of scope for this crate.

## Layout

```
Cargo.toml
src/main.rs        CLI dispatch and session orchestration
src/cli.rs         hand-rolled argument parsing (tested)
src/devicetree.rs  /chosen + reserved-memory parsing and validation (tested)
src/capture.rs     read-only /dev/mem mmap capture, provenance, probe output
src/image.rs       ARGB/XRGB image, pitch-aware buffers, PPM fixtures (tested)
src/dissolve.rs    threshold band, damage accumulation, erase engine (tested)
src/pacing.rs      monotonic clock and absolute frame schedule (tested)
src/display.rs     SimpleDRM selection, modeset, DirtyFB, CLOSEFB, guard
src/drm_uapi.rs    explicit ADDFB2/CLOSEFB UAPI wrappers (tested)
src/handoff.rs     root-only yield socket server/client (tested)
src/stats.rs       measured counters and summary output (tested)
src/signals.rs     self-pipe TERM/INT/HUP handling
src/systemd.rs     sd_notify best-effort READY/STATUS
integration/       opt-in dracut/systemd unit files
```
