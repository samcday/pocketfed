# Native Sargo FPC protocol and diagnostic

This source implements the inspected Sargo FPC TA/HAL wire format and the
reviewed kernel QSEECOM/misc-device ABI. See [protocol.md](protocol.md) for the
FPC protocol, [gatekeeper.md](gatekeeper.md) for enrollment authorization, and
[the implementation tracker](../../devices/google-sargo/fingerprint.md).

`fpc-qsee-probe` has no default hardware action. Its two explicit modes are:

```text
fpc-qsee-probe --initialize
fpc-qsee-probe --touch-window SECONDS
```

The second mode accepts 1–120 seconds. Both require root access to the native
sensor and an already-loaded `fpctzappfingerprint` app. The probe does not load
firmware or enroll/identify a fingerprint; capture readiness is not a match.
It reports command status and GPIO IRQ metadata without returning images,
templates, passwords or authentication tokens. SIGINT/SIGTERM cancel the wait
and take the normal cleanup path. It has not run on the real phone yet.

The source is shared into the libfprint driver by its packaging patch. Session
objects must be initialized with `FPC_QSEE_SESSION_INIT` or zeroes; sensor
objects must start with `.fd = -1`. Each object permits one caller at a time.
Close only after any blocking exchange or worker has completed.

`make check` exercises separate firmware dispatcher/command failures, gallery
match predicates, bounded response lengths, TEE shared-memory and session
cleanup, Gatekeeper frame/token checks, and sensor cancellation/timeout/stale
IRQ behavior with synthetic boundaries. These do not establish live hardware
compatibility. Stock images and credentials are not test fixtures or package
inputs.

The probe RPM has no services or activation scriptlets. Real-device use follows
the [controlled kernel trial](../kernel-fingerprint/trial-procedure.md).
