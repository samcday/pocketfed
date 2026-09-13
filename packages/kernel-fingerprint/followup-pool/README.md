# QSEECOM invoke-pool regression checks

Sargo fingerprint initialization could complete and then leave firmware-loader
shutdown stalled, followed by a watchdog reset. The kernel follow-up reuses the
device-owned TZ pool for invoke staging, keeping coherent backing mappings alive
between commands. Each staging allocation is still fully cleared and released.
The userspace-mapped TEE pool stays separate.

The kernel change is on
[kernel PR #3](https://github.com/samcday/linux/pull/3),
based on preserved kernel .11 source at commit
`132283913205a1db1d57fc3e563eea8224f5b79a`. The accompanying patch is the same
driver change; the kernel repository also carries the .12 packaging release.

Run the synthetic checks against that kernel checkout:

```sh
python3 packages/kernel-fingerprint/followup-pool/test-invoke-pool.py /path/to/linux
```

The runner extracts the actual validation and invoke functions and compiles them
with mocked allocation and SCM boundaries. It checks 24 success/error cases at
both 4 KiB and 64 KiB page sizes, using GCC with optimization, LTO, warnings as
errors and undefined-behavior traps. It rejects per-invoke pool creation or
destruction and checks every staging byte before release. Mutations that remove
clearing or shorten it to the payload size must fail. Use `--expect-per-invoke`
against the unchanged .11 checkout to verify rejection of the original allocator.
GCC must be available at `/usr/bin/gcc`; no kernel build or phone access is needed.
The fixture does not model DMA, cache coherence or concurrent kernel execution.

Completed hardware and packaging evidence:

- A disposable comparison used the same kernel and userspace, changing only the
  allocator-selection parameter. Both variants completed initialization, 1,000
  allocation/releases, deep sleep and session close. The original allocator then
  stalled during loader shutdown and reset; the reused pool completed shutdown.
- Repetition with pool reuse passed 50 native cycles across ten firmware-service
  lifetimes: 50,000 allocation/releases and 30 service stops. UART remained
  responsive without observed RPMh timeouts, CPU lockups or spontaneous resets.
- Production kernel .12 built successfully for ARM64 in
  [COPR 10980882](https://copr.fedorainfracloud.org/coprs/build/10980882).
  The signed packages passed image comparisons and booted with SELinux enforcing.
- Installed testing passed 50 ordinary fprintd Claim/Release cycles across ten
  service lifetimes and 50 explicit service stops in 58.35 seconds. It used
  packaged libfprint, made no capture requests, and retained UART confirmation of
  every cycle and stop. The boot stayed unchanged without observed stall signatures.

Host and ARM64 synthetic runs and strict driver checkpatch also passed. Kernel
fix commit `cad152be638f42256f26d3566842d67edc1688c1` is included in built release
commit `3ad4e5eac8aa16c1e6dcf291fdec4fb906f803d0`; the later review commit only
removes trailing changelog whitespace. The trial-only module parameter is absent
from the production source.

Physical Settings testing passed additional finger enrollments, a dozen more
dialog reopens and sampled matching/nonmatching feedback. A normal reboot of
the same .12 deployment preserved enrollment metadata and automatically started
the fingerprint socket. After the initial PIN login, the user confirmed roughly
six further cycles alternating Phosh lock/unlock, multiple enrolled fingers,
wrong-finger rejection, PIN fallback and Settings tester matching/nonmatching
feedback. The phone remained responsive on the same boot, with SELinux enforcing
and no observed UART stall signatures. The ordinary PIN configuration stayed
unchanged.

The requested Settings and Phosh acceptance is complete. The brief Phosh
wrong-fingerprint message remains a UX follow-up. Transient authentication workers
also retain failed-unit bookkeeping for exit status 1, which covers authentication
failure and client disconnect; none in the final snapshot timed out or crashed.
The logs do not distinguish each individual transaction's reason for that status.

These checks support the allocator change but do not prove the underlying
platform fault or long-term reliability. Private device logs, firmware,
credentials and biometric templates are excluded from this review.
