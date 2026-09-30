# QSEECOM invoke-pool comparison, 13 September

This is an experimental module-only candidate, not an installed update or an
accepted fingerprint fix. It uses the exact `.11` source commit
`132283913205a1db1d57fc3e563eea8224f5b79a` and packaged GCC 16.2.1.
The candidate retains the packaged kernel, DTB and all other module bytes.
All 65 imported symbols resolve against its packaged symbol table, and module
vermagic matches. Native header preparation removed unavailable Rust/tool
features from its build configuration; none of those changed symbols occurs
in any of the 594 C source/header dependencies compiled for this module. The
full delta is recorded in the candidate provenance. The trial module is unsigned;
no signature-enforcement or lockdown policy is weakened.

The default-off `reuse_invoke_pool` module parameter selects the driver's
existing long-lived TZ pool instead of creating and destroying a coherent
pool per invocation. Request, response and auxiliary buffer layout, copying,
zeroing, secure calls and return handling are unchanged. Individual chunks
are still freed; this experiment retains the pool's backing mappings, not
application-owned persistent command contents. A positive result would narrow
the allocator/mapping/lifetime investigation, not prove a specific root cause.

The baseline and reuse profiles boot the same module and disposable userspace
on daily sam-sargo, serial `994AY18RSD`, using its exclusively assigned A5069RR4
UART. The native test pins itself to CPU 7, resets the sensor, sends INIT,
performs 1,000 8 KiB CMA allocation/release operations, sends DEEP_SLEEP and
closes. No fingerprint capture, authentication, database, enrollment or
credential-recovery API is called. The controller stops the isolated secure
service chain after a returned result. There is no timeout kill or automatic
retry of a pending secure call. Original authentication services remain masked.

USB-root hosting must remain alive until the disposable session has ended.
These runs cannot establish behavior after USB loss. No flashing, slot change
or installed daily-driver deployment is part of this comparison.

Source lives here and in `/var/home/sam/src/pocketfed-kernel-fpc-pool`. Generated
build and overlay material is in `out/fingerprint-kernel-pool-20260913`; the
sealed candidate is `out/liveboot/candidates/sargo-fpc-pool-20260913`. Native
compilation with warnings as errors and the patch style check passed. Runtime
acceptance is still pending.

## Generation 04: preserve the native result

Generations 02 and 03 exposed a harness defect: first-boot presets removed an
`/etc` mask of `serial-getty@ttyMSM0.service`. Starting that getty hung up the
console used by the native probe. Generation 03 reproduced a kernel lockup
around loader teardown, but lost the native output and exit status; it cannot
establish which parts of the intended probe sequence completed.

Generation 04 uses the boot argument
`systemd.mask=serial-getty@ttyMSM0.service` and checks that the live unit is masked
and inactive before starting the loaders. Its controller has no controlling
terminal. `trial_evidence.py` drains both native output pipes, keeps raw files,
and relays bounded stage records through `/dev/kmsg`. It records the child exit
status and verifies INIT, all 1,000 allocations, DEEP_SLEEP and session close
before requesting loader teardown. The result therefore survives a subsequent
blocked `systemctl stop`. The native sequence itself is unchanged.

The three host regression checks in `test-trial-evidence.py` cover concurrent
pipe draining, console-write failure, child-launch failure, and rejection of
an exit-zero result with missing stage markers. They passed, as did the ARM64
build with `-Werror` and fixture label verification under enforcing SELinux.
Both profiles use the same fixture, candidate and snapshotted kboop tools;
`pair-validation-04.json` records that the allocator flag is their only profile
difference.

The first generation-04 host attempt timed out before fastboot and booted no
guest. The next attempt verified firmware, the runtime getty mask, successful
INIT and 900 allocation iterations before a user-confirmed manual power-off.
It is an interrupted experiment, not a kernel failure or completed baseline.
Those records are preserved in the baseline run's `attempts/` directory.

The uninterrupted comparison produced the following results:

| Stage | Original per-invoke pool | Reused pool |
| --- | --- | --- |
| Runtime getty mask and stock firmware | Verified | Verified |
| INIT, 1,000 allocations, DEEP_SLEEP, session close | Verified; native exit 0 | Verified; native exit 0 |
| FPC loader stop | Requested at 45.828 s; no completion | Completed successfully |
| Remaining loader/supplicant stops | Not reached | Completed successfully |
| Subsequent state | RPMh timeout at 56.10 s; reset without a coordinator recovery command; installed boot reports watchdog | Trial passed at 47.30 s; UART HELP answered at 105.21 s; explicit SysRq reset answered at 366.03 s |

Both `observation.json` files preserve these conclusions and the UART hashes.
This is one controlled failing/passing pair, not installed acceptance or proof
of a particular memory-lifetime defect. The original-pool run now has the
complete native evidence that generation 03 lacked. The first, manually
interrupted generation-04 run is excluded from this comparison.

Generation-04 artifacts:

- `out/fingerprint-kernel-pool-20260913/native-build-04/build.json`
- `out/fingerprint-kernel-pool-20260913/pair-validation-04.json`
- `out/liveboot/fixtures/sargo-fingerprint-pool-04-20260913/fixture.json`
- `out/liveboot/runs/sargo-fingerprint-pool-baseline-04-20260913/`
- `out/liveboot/runs/sargo-fingerprint-pool-reuse-04-20260913/`

## Generation 05: repeated native and loader lifetimes

The next bounded test uses the same candidate with reuse enabled. It runs 50
separate native processes, restarting the isolated firmware services after
each group of five. Each process performs the same initialization/allocation/
sleep/close sequence, with a private, exclusive receipt for its numbered cycle.
The controller checks each complete result before continuing or requesting a
service stop. Failed native verification or loader stop ends the sequence;
neither is retried. No pending secure call is timeout-killed.

Three host checks in `test-lifetimes.py` passed: the 50-cycle/10-lifetime ordering,
stopping without cleanup after an unverified native result, and refusing the
next lifetime after a failed loader stop. The native ARM64 build with `-Werror`
passed.

The hardware run passed all 50 cycles, all 10 service lifetimes and all 30
service stops. Each cycle verified INIT, 1,000 allocation/release operations,
DEEP_SLEEP, session close and native exit 0. The complete trial took 341.07 s,
covering 50,000 allocation/release operations. UART HELP answered at uptime
447.23 s, and the explicit end-of-trial reset answered at 530.33 s. No RPMh
timeout, soft-lockup, RCU-stall or secondary-CPU-stop failure marker appeared.
The per-cycle evidence and UART hash are recorded in
`out/liveboot/runs/sargo-fingerprint-pool-repeat-05-20260913/observation.json`.

These are native initialization and cleanup tests. They do not exercise
fprintd Claim/Release, database loading, enrollment or authentication. Those
remain later acceptance steps against the user's installed state.

The source checkout has now moved from its detached experimental state to
`codex/sargo-fingerprint-invoke-pool-fix` for production packaging. The sealed
experimental candidate and original default-off patch remain unchanged.
The proposed production patch and synthetic tests are in
`packages/kernel-fingerprint/followup-pool/`.
