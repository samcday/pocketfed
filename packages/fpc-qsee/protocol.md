# Sargo FPC QSEE protocol, SP2A.220505.008

This is an interoperability description recovered by static analysis of the
Pixel 3a's stock firmware. The command encoders have hardware-free tests. No
successful live initialization, capture, enrollment, match or persistence is
claimed by this document. Protocol compatibility with other FPC firmware must
be established separately.

## Evidence and provenance

Read-only inspection on 2026-09-11 confirmed vendor build
`google/sargo/sargo:12/SP2A.220505.008/8782922:user/release-keys`. The existing
`vendor_b` device-mapper table was `0 991624 linear 259:61 1759464`.
The following files were copied to a private local analysis directory from
that mapping using read-only debugfs; proprietary binaries are not part of this
package.

| File within vendor | Bytes | SHA-256 |
| --- | ---: | --- |
| `firmware/fpctzappfingerprint.mbn` | 691540 | `e947fd8b081b47be9bd75c87cbd95a79fd8955b9d3310631680ca47fd76997e8` |
| `firmware/fpctzappfingerprint.mdt` | 7208 | `3d23e9a669df46ab3bc50af44215670a5de60be1f623e0e20e69e0bdcce3ab71` |
| `bin/hw/android.hardware.biometrics.fingerprint@2.1-service.fpc` | 63360 | `11b4f4069ef6fd8b06147be8a696944aa50d664c6969a30f40ee224440a6de48` |
| `lib64/libQSEEComAPI.so` | 31784 | `6ae96f5eda8f4411c42f9323cabe82f4ecea58a1692d409df21892aa1ba71859` |

The trusted application (TA) is ELF64 AArch64. Although it has no section
table, its PT_DYNAMIC data supplies 1101 dynamic symbols and relocation
records. Function addresses below are ELF virtual addresses before relocation,
not physical addresses. The dependency name is `libcmnlib.so`; ELF class,
rather than that generic SONAME, determines the required QSEE common-library
architecture. The dynamic module registry has seven entries: common target12,
biometrics11, sensor10, KPI9, navigation8, hardware authentication3 and files2.

Public stock [device tree](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/arch/arm64/boot/dts/google/sdm670-b4s4-fingerprint.dtsi)
and [platform driver](https://android.googlesource.com/kernel/msm/+/refs/heads/android-msm-bonito-4.9-android12L/drivers/input/misc/fpc_fingerprint/fpc1020_platform_tee.c)
establish GPIO121 IRQ and GPIO134 reset. The `fpc,fpc1020` compatible identifies
the driver family. The fitted silicon revision and physical secure SPI
controller have not been measured. Normal-world Linux requires reset and IRQ
control; it does not issue the biometric SPI transactions in this architecture.

## Transport

Stock HAL address `0xc6e0` opens `/vendor/firmware/fpctzappfingerprint` using
QSEECom_start_app with a 128-byte primary shared buffer. It allocates an ION
auxiliary buffer, rounded to a 4096-byte allocation. The invocation at `0xcb80`
uses a 64-byte request followed by a 64-byte response in the primary buffer.

The packed outer request is:

| Byte offset | Type | Meaning |
| ---: | --- | --- |
| 0 | little-endian u32 | Auxiliary buffer length |
| 4 | little-endian u64, **unaligned** | Auxiliary physical address |
| 12–63 | bytes | Padding, zero in this implementation |

The TA wrapper `0x46e8` requires request length at least12, response length at
least4, and auxiliary length at most1MiB. It prepares shared access, copies the
auxiliary data into secure memory, dispatches, copies the result back and
finalizes shared access. The first response word is a signed dispatcher status.
It is separate from the command result inside the auxiliary buffer.

The shipped HAL calls **QSEECom_send_modified_cmd**, not its `_64` variant.
Its descriptor has one DMA fd and patch offset4. The exact library makes the
plain API a 32-bit-address patch, and `_64` a 64-bit-address patch. Thus stock
relies on a below-4GiB allocation and a zero high address word, while the TA
reads the complete 64-bit field. A native transport may patch all64 bits at
offset4. It must support the unaligned position and keep the DMA mapping alive
through the call; never pass a userspace virtual address as the physical field.

An auxiliary command starts with little-endian words `{target, command,
command_result}` at offsets0,4,8. The protocol library initializes result words
to an error sentinel. The injected callback returns a transport error and the
separate dispatcher result. Command data are interpreted only after both
transport and dispatcher succeed. Buffers containing HATs or wrapped keys must
not be logged.

## Sensor target10

The handler at `0x1418` requires at least84 bytes; stock uses88 logical bytes
inside its page allocation. Results are signed words at offset8; capture detail
is a word at offset12. Commands start and stop secure sensor communication.

| Command | Operation | Static interpretation |
| ---: | --- | --- |
| 0 | initialize | `fpc_device_init`; result0 succeeds |
| 1 | check finger lost | Returns0 or1 for two sensor states; stock capture ignores this result |
| 2 | arm finger release | `finger_lost_wakeup_setup` |
| 3 | arm finger contact | `wakeup_setup` |
| 4 | capture and qualify | Result0 leaves a qualified image for biometrics |
| 5 | deep sleep | Result0 succeeds |
| 6 | OTP support | Query; not needed by the initial client |
| 7 | OTP information | Query; payload details not yet decoded |

The stock capture routine at HAL `0xb488` performs:

1. Enable the kernel IRQ wake flag.
2. Send sensor command2, wait until IRQ level1, then send command1. Its return
   is ignored in this routine.
3. Send command3, wait until IRQ level1, then send command4.
4. On command4 success, disable IRQ wake but leave the image available for a
   biometric command. On failure/cancellation, disable wake and send command5.

The IRQ waiter at `0x9578` reads the GPIO level before polling. It waits on the
IRQ and a cancellation pipe, acknowledges the sysfs notification, and rereads
the level. An IRQ is a wake signal, never a match or capture-success result.

Capture result `0x107` triggers at most four rapid attempts; waiting more than
500ms resets that rapid-retry count. Stock reports Android acquired-insufficient
after exhausting the attempts. `0x105` is reported as acquired-too-fast and
recaptured. `0x108` is silently recaptured by the enrollment loop. Negative
hardware results include `-212`; general communication failure is `-206`.
The exact sensor-state meanings of command1's boolean remain unconfirmed.

## Biometrics target11

Handler `0x964` requires40 bytes. Offset12 is the principal in/out word; offsets
16–39 hold six additional words. The command table is at `0x45eb4`.

| Command | Operation | Payload |
| ---: | --- | --- |
| 0 | begin enrollment | No initial remaining-count output |
| 1 | process enrolled sample | Output remaining at12 |
| 2 | finish enrollment | Output new template ID at12; requires valid enrollment authorization |
| 3 | identify current image | Output template ID at12, decision at28 |
| 4 | update matched template | Output updated boolean at12 |
| 5 | unsupported | Do not issue |
| 6 | create empty database | Destroys the current in-memory database |
| 7 | enumerate IDs | Input capacity at12, output count at12 and IDs at16 |
| 8 | delete template | Nonzero ID at12; zero is rejected with -210 |
| 9 | set active group | Group ID at12 |
| 10 | get database ID | Output u64 at16 |

The database supports five template IDs. Treat an enumeration count abovefive
as malformed, including when dispatcher and command report success.

Enrollment requires a successful capture before each command1. The HAL's loop
at `0x7a48` handles command results as follows:

| Result | Stock behavior |
| ---: | --- |
| 0 | Enrollment samples complete; immediately issue command2 |
| `0x10f` | Accepted progress; report good acquisition and remaining count |
| `0x110` | Terminate with unable-to-process error |
| `0x111` | Terminate with vendor error1000 |
| `0x112` | Report partial acquisition and retry |
| `0x113` | Report progress plus vendor acquisition1000 |
| `0x114` | Report dirty-image acquisition and retry |

The initial stage count is not a constant in this HAL ABI. Do not infer
completion from a touch, from a decreasing count, or solely from count0 while
the command result is nonzero. On completion, require successful command2 and
a nonzero new ID, then successfully persist before reporting enrollment saved.

Identification requires all of: transport0, dispatcher0, command0,
template-ID nonzero, and decision1. Command success alone includes nonmatches.
The six diagnostics at16–39 are retained by the library, but names other than
decision have not been confirmed. `fpc_identify_matched()` implements this
strict predicate. Callers must also check that the returned ID belongs to the
requested user's enrollment before reporting a successful verification.

Identification completion is a separate required step. The stock HAL calls
target11 command4 after both nonmatches (`0x74dc`) and matches (`0x7610`), then
stores the database only when the returned update boolean is nonzero. Inside
the TA, command4 calls `fpc_algo_identify_update` and `fpc_algo_end_identify`;
`FpcBioIdentifyUpdate` transitions algorithm state2 back to1 (and4 back to3).
Reloading the database is not a substitute for this completion. The first
native match passed on test-sargo, but the following identification failed
with command `-211` while this step was absent. That status is not treated as a
normal nonmatch: the TA's error conversion maps algorithm error `-115` to it.
The corrected driver requires successful completion before reporting a result
and discards in-memory adaptation by reloading saved records next time.

## Database files and listeners

Target2 handler `0x53b8` implements command11 load and12 store. Offset12 is the
path byte count including its NUL terminator, and offset16 begins the path.
Load destroys the current in-memory database before reading, so a failed load
does not preserve a usable previous database. An empty-database creation must
be deliberate, rather than an automatic response to arbitrary I/O failure.

File operation wrappers use QSEE storage calls; a listener service must answer
them. This lane has not observed which requests this FPC build emits at runtime.
The native supplicant supplies the Qualcomm FS listener10 and GPFS listener28672.
Store only the opaque output produced by the TA in a dedicated Linux state
root; do not point the client at Android's enrolled-template database.

## Authentication target3 and Keymaster

Handler `0x5acc` requires at least24 bytes. Most results are at offset8.

| Command | Operation | Payload |
| ---: | --- | --- |
| 1 | set authentication challenge | u64 challenge at16 |
| 2 | get enrollment challenge | Output u64 challenge at16 |
| 3 | authorize enrollment | Length69 at12, HAT at16 |
| 4 | get successful authentication HAT | Length69 at12, output HAT at16 |
| 5 | import wrapped authentication key | Length at12, opaque blob at16 |
| 6 | enrollment timeout | Seconds at12, start boolean at16, **result at20** |

The stock FPC HAL's Keymaster client at `0xcd08` opens `keymaster64` with a
1024-byte shared buffer. It sends a padded64-byte request beginning with words
`{0x205,2}` and receives up to960 bytes. Response words are status, blob offset
relative to the response, and blob length; the wrapped blob follows. Bounds
must be checked before passing it to FPC target3/command5. The FPC TA unwraps
the blob inside secure world and checks that its source application name is
`keymaster64` (`fpc_ta_hw_auth_unwrap_key`, `0x60fc`). The normal-world client
does not receive or synthesize the underlying HAT signing key.

`fpc_check_enrollment_allowance` at `0x58b4` calls validation at `0x5924`.
Enrollment requires an imported key, a nonzero fresh TA challenge, a HAT bound
to that challenge, and a valid HMAC-SHA256. The challenge expires after roughly
ten minutes. HMAC covers the first37 bytes of the packed69-byte HAT; the final32
bytes contain the authenticator. Version must be0. The packed fields are a
version byte, three64-bit values (challenge, secure user ID, authenticator ID),
authenticator type32, timestamp64 and HMAC32; Android specifies network byte
order for type and timestamp. The remaining fields follow the platform's
native little-endian serialization.

An all-zero or challenge-only token does **not** satisfy this FPC build's
validation. In particular, completing enrollment into a temporary RAM database
still passes through the authorization check. This is a core dependency for
successful enrollment, not a persistence-only requirement.

## Remaining Gatekeeper work

The public [Qualcomm Gatekeeper analysis](https://github.com/wrobelda/goodix-fp-spi-linux/blob/master/docs/06-Gatekeeper-protocol.md)
offers a candidate protocol from a different Xiaomi firmware: resident
`keymaster64`, version negotiation `0x200` / `0x207`, then CBOR enrollment
`0x21001` and verification `0x21002`. The verification response carries the
signed fields needed for a HAT. Its author has not yet demonstrated successful
native Linux credential enrollment and signed-HAT fingerprint enrollment.
Those command numbers and negotiation values are not yet established for Sargo.

Sargo has fixed `keymaster_a` and `keymaster_b` partitions (524288 bytes each)
and no Keymaster filename in vendor/firmware. A metadata-only device inspection
confirmed both start with ELF64 AArch64 headers and have identical SHA-256
`8f800f36d6eef63373dc502462c5f52d1d779dd078e0ae429108ea86fcbb261a`.
No Keymaster binary bytes were returned from the device. This is consistent with, but does
not itself prove, a resident bootloader-loaded application. Its vendor includes
`android.hardware.gatekeeper@1.0-impl-qti.so`, `libkeymasterutils.so` and
`libqtikeymaster4.so`. These libraries were identified by directory metadata;
their contents have not been copied or analyzed in this lane.

The missing evidence is the Sargo Gatekeeper command serializer, its version
negotiation, and the legitimate Linux-owned credential provisioning and verify
flow that produces a challenge-bound HAT. Static analysis of the fixed vendor
Gatekeeper implementation and its serialization dependency would answer the
wire-layout questions. It does not require reading Android password handles,
synthetic-password material, keystore contents, templates or any user data.
Actual provisioning and HAT production require a separately implemented
credential service and runtime validation. The FPC driver should consume its
token rather than inventing authorization.

## Hardware-free checks

`test-protocol.c` verifies fixed wire bytes, the unaligned64-bit pointer,
Keymaster response bounds, enumeration capacity, and rejection of matches on
transport/dispatcher/command errors, untouched replies, zero IDs or a nonmatch
decision. Run:

```sh
cc -std=c11 -Wall -Wextra -Werror protocol.c test-protocol.c -o test-protocol
./test-protocol
```

These checks passed on the development host, including a build using
`-fsanitize=undefined -fsanitize-undefined-trap-on-error`. The transport's
separate wrapped-ioctl tests passed with those flags too. Address sanitizer
linking was unavailable because the host lacked its runtime library. These
checks do not establish live hardware compatibility.
