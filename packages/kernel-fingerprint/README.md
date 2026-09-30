# Sargo fingerprint kernel trial

This prepares `7.1.2-0.pocketfed.sdm670.10.fc46` from the complete `.9` camera
release (`ecf4d556abc6bf35c5f40221ce5bc56279cb57d6`). Existing phone fixes and the
LC898219XI lens lifecycle fix remain in its ancestry. The isolated source is
`/tmp/sargo-fingerprint-kernel`, branch `codex/sargo-fingerprint`.

The changes provide the kernel transport and electrical controls needed by a
native FPC userspace driver. They do not establish successful fingerprint
initialization, enrollment, matching, or desktop authentication on hardware.
Kernel installation must use a COPR build of this source RPM.

## Source and implementation

The first patch imports Dawid Wróbel's experimental [QSEECOM TEE branch](https://github.com/wrobelda/linux/tree/662435b853d865d360507f5daee6ff309838c5ca)
as its exact diff from v7.1. The next patch adapts and repairs it:

- Contiguous firmware assembly supports little-endian ELF32 and ELF64, checks
  header and segment bounds, and copies MDT plus `.bNN` payloads in program
  header order. The existing remoteproc MDT loading path is unchanged.
- Application names are snapshotted before checking shared memory; transfer
  size arithmetic is checked; unaligned 32-bit and 64-bit address fixups work.
- Sessions retain the application while invoking it. Duplicate privileged
  loads reuse the current registry entry. New loads cannot evict active
  identities, session and application generations do not wrap, and failed
  unloads retain their identity for reuse.
- Listener registration handles error pointers and allocation cleanup. Returned
  listener shared-memory references remain valid through receiver-context
  close, including timeout and concurrent deregistration paths.
- Privileged common-library loading uses QSEE APP_MGR command 7. Successful
  loads are remembered for the boot lifetime in the built-in SCM layer.

The electrical companion follows Google's [Sargo fingerprint DTS](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/arch/arm64/boot/dts/google/sdm670-b4s4-fingerprint.dtsi)
and selected [FPC platform driver](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/drivers/input/misc/fpc_fingerprint/fpc1020_platform_tee.c):
GPIO 134 reset, GPIO 121 rising-edge IRQ, 2 mA pin drive, IRQ pull-down, and
reset high 100 µs / low 5 ms / high 5 ms. The node is added only to Sargo.
These sources establish board wiring and the driver family, not a measured
sensor chip ID. No SPI bus or supply mapping is invented.

## Electrical userspace ABI

The new `/dev/fpc1020` misc device defaults to mode 0600 and permits one open
file. The driver reports the fixed board firmware name `fpctzappfingerprint`
through read-only `/sys/class/misc/fpc1020/firmware_name`. The parent platform
node has compatible `google,sargo-fingerprint`, followed by `fpc,fpc1020`.

[fpc1020.h](fpc1020.h) is the exact userspace header. The event is 16 bytes:
`u64 sequence`, `u32 level`, `u32 reserved`. Values use the host ABI; the
reserved field is zero. IRQs increment the sequence. `poll()` becomes readable
when it differs from the file's consumed sequence; `read()` returns one event
and consumes that sequence. `O_NONBLOCK` reads return `EAGAIN` when unchanged.

- `FPC1020_IOC_GET_IRQ`, `_IOR('F', 2, struct fpc1020_irq_event)`, snapshots the
  current GPIO level and sequence without consuming an event. Check it before
  waiting, since the line can already be asserted before capture starts.
- `FPC1020_IOC_RESET`, `_IO('F', 0)`, performs the stock reset sequence.
- `FPC1020_IOC_SET_WAKEUP`, `_IOW('F', 1, u32)`, accepts only 0 or 1. Wakeup
  starts disabled and is disabled on close. An enabled IRQ holds wake for 1 s.

Probe holds the sensor in reset until userspace explicitly resets it. GPIO
access is serialized against removal; open files retain the state by kref.
Removal wakes readers, returns `ENODEV` for reads/ioctls and `POLLERR|POLLHUP`
for polling, and keeps private data alive until all open references close.
Interrupt events never represent a biometric match.

## QSEECOM userspace ABI

Select the TEE device by `TEE_IOC_VERSION.impl_id == TEE_IMPL_ID_QSEECOM` (5 in
this experimental downstream branch), not by a hard-coded minor. This is a
provisional interface, not an upstream-assigned ABI. `qseecomtee.ko` exposes a
client TEE node and a privileged TEE node. The latter requires `CAP_SYS_ADMIN`.
The existing QCOMTEE/smcinvoke driver serves a different interface.

A client opens a session with an all-zero UUID and one MEMREF_INPUT containing
a NUL-terminated application name. A normal privileged load uses the same
parameters and fetches the corresponding firmware files through the kernel
firmware loader. The returned positive session holds the application; keep a
loader session open while clients may need it. Bootloader-resident apps can be
attached by name and are never unloaded by this driver.

For common libraries, privileged OPEN_SESSION takes a name MEMREF_INPUT and
VALUE_INPUT `{a=1,b=0,c=0}`. Only `cmnlib`/ELF32 and `cmnlib64`/ELF64 are accepted.
The positive session ID acknowledges a boot-lifetime load: closing it does not
unload the library. Repetition succeeds only after this Linux boot observed a
successful load. Arbitrary firmware errors are not treated as "already loaded".
No common library or keymaster application is loaded automatically.

INVOKE uses function 0, request MEMREF_INPUT and response MEMREF_OUTPUT, then
optional pairs of VALUE_INPUT `{a=offset,b=width,c=0}` and MEMREF_INOUT. Width is
4 or 8, little endian, and need not be aligned. Width 4 rejects addresses above
4 GiB. Stock Sargo's packed request has length at byte 0 and a 64-bit address
at byte 4; a width-8 patch at offset 4 matches its parser. Userspace supplies the
protocol's 64-byte request and 64-byte response padding. Auxiliary buffers and
responses are copied back only after transport success. Protocol status remains
in those buffers, not in a synthesized biometric result.

One supplicant receiver serves the registered listeners. It must never issue
SCM calls while answering a listener. See the patched
`Documentation/tee/qseecom.rst` for the registration and receive/send protocol.

## Validation and remaining hardware checks

`build.json` pins the source, bundle, patches, source RPM, hashes and commands.
`validation/` contains the ARM64 compile, image assembly tests, schema validation,
style checks, package configuration and full ARK source-RPM generation log.

GCC 16.1.1 with `W=1` compiled the linked QSEECOM driver object, SCM, MDT loader,
FPC companion, and Sargo DT. A separate minimal ARM64 build linked `vmlinux`,
`qseecomtee.ko` and `fpc1020.ko` through modpost without unresolved exports.
Its reduced configuration emits existing syscall-table override warnings; the
changed driver objects compile without warnings under the defconfig check. The adaptation diff and companion pass strict
checkpatch with zero errors, warnings or checks. Both DT schema validation and
validation of the compiled Sargo node passed. The generated ARK config enables
both new drivers as modules and preserves all four camera modules.

The fixture compiles the actual production contiguous-loader functions with
mocked firmware I/O and undefined-behavior traps. It checks ELF32/64 assembly,
malformed headers, segment and destination bounds, overflow, and exact payloads.
The exact stock Sargo ELF64 MDT also passes: eight segments, 680905 assembled
bytes. No extracted firmware or biometric data is included here.

The SCM lock serializes callers and ordinary INCOMPLETE listener requests are
handled. CONTINUE_BLOCKED/reentrant listener handling is not implemented;
BLOCKED_ON_LISTENER returns `EBUSY`. This is a real compatibility limit to check
before continuing with commands on the trial. A malformed or interrupted secure
call can require reboot. Failed listener deregistration deliberately retains its
buffers and callback to avoid secure-world use-after-free; that can pin the
module until reboot. These cases are not proven by compilation or the fixture.

The kernel subtask performed no phone access or live commands. Initial device
acceptance must verify the matching `.10` kernel and DTB, positive misc/TEE
discovery, IRQ level/counter and reset operation, common-library and app load,
listener completion, cancellation, and unload. Enrollment and authentication
remain userspace and hardware acceptance work. Preserve a complete known-good
boot deployment for trial recovery, including its boot template and initramfs.

## Reproduce

```sh
python3 packages/kernel-fingerprint/test-image-loader.py /tmp/sargo-fingerprint-kernel

# Prepared .10 source; the release commit is already present.
cd /tmp/sargo-fingerprint-kernel
PATH=/usr/bin:/bin CCACHE_DISABLE=1 make NO_CONFIGCHECKS=1 \
    UPSTREAMBUILD_GIT_ONLY=0 DIST=.fc46 DISTLOCALVERSION= \
    dist-check-release dist-srpm
```

The proposed isolated target is
`samcday/kernel-sdm670-mainline:custom:fingerprint-trial`,
`fedora-rawhide-aarch64`. The coordinating task submits and verifies its binary
artifacts; this preparation does not publish to the normal kernel feed.

## Boot and rollback preparation

[trial-procedure.md](trial-procedure.md) records the fresh read-only deployment
snapshot, transient eSIM overlay, exact preservation requirements, proposed
image build step, DTB replacement, locked staging and rollback boundaries.
The local DTB tool is tested; the container kernel step awaits COPR binaries.
