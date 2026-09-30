# QSEECOM invoke staging cleanup follow-up

This is a COPR-built follow-up to kernel `.10`, commit
`288962298f4aee8e67ade2c566cf77d3c95f5b22`. It is **not included** in COPR
10973618 or local image
`83cc5287c9ae65449e51d5f45c5e495ddca48dba45416e4f1f85d49afe6535a0`.
The follow-up is committed as `.11` and its source RPM passed ARK release/source
checks. [COPR 10973843](https://copr.fedorainfracloud.org/coprs/build/10973843)
succeeded for ARM64; all seven runtime RPM signatures and digests are verified.
[build11.json](build11.json) records the exact commits, source RPM and downloaded
artifacts. The `.11` stage is now included in the locally validated masked
image `671197f9f3bf`; no device change has been made. The existing
parent release metadata remains the record of the reviewed `.10` artifacts.

[The patch](0001-tee-qseecom-wipe-application-invoke-staging.patch) adds
`memzero_explicit(b, bc.initial_size)` at the application invoke's shared
`out_free` label, before `qcom_tzmem_free()` and pool destruction. Successful
response and auxiliary copy-back finish first. The same cleanup handles
auxiliary mapping failure, physical-address lookup failure, 32-bit address
overflow, and secure-call errors after allocation. Earlier validation or
allocation failures have no populated staging buffer to erase.

## Allocation evidence

The reviewed source is `/tmp/sargo-fingerprint-kernel`:

- `drivers/tee/qseecom/core.c` allocates a dedicated static pool and one chunk
  of exactly `PAGE_ALIGN(need) + PAGE_SIZE` bytes. `need` includes request,
  response and every auxiliary buffer and is bounded by 16 MiB. Clearing
  `bc.initial_size` covers the complete allocation, including padding.
- `drivers/firmware/qcom/qcom_tzmem.c` obtains pool areas with
  `dma_alloc_coherent()` and suballocates their kernel virtual addresses with
  `gen_pool`. Both the area and chunk sizes are page aligned; the invoke's
  already-aligned size is unchanged. The CPU pointer is an ordinary `void *`,
  not an `__iomem` mapping. `qcom_tzmem_free()` releases allocator bookkeeping;
  pool destruction calls `dma_free_coherent()`. Neither explicitly clears data.
- `include/linux/string.h` implements `memzero_explicit()` using `memset()`
  followed by `barrier_data()`, preventing dead-store elimination.
  `drivers/firmware/qcom/qcom_scm.c:qcom_scm_ice_set_key()` already uses this
  helper on a `qcom_tzmem_alloc()` buffer before its automatic release.

This patch leaves firmware loading, persistent listener buffers, user-mapped
TEE shared memory and secure-world lifecycle semantics unchanged. It does not
resolve the existing blocked-listener/continuation limitation or establish
that secure firmware has finished using memory on every error; it clears the
allocation immediately before the existing release point.

## Focused validation

[The fixture](test-invoke-wipe.py) compiles the production memref validation,
patch validation and invoke functions, plus the actual `memzero_explicit()`
definition. Only session, allocation, shared-memory and SCM boundaries are
mocked. Its free hook checks every allocation byte before permitting release;
synthetic SCM writes and injected faults poison the padding as well as payloads.
It verifies output copy-back precedes clearing and caller buffers remain intact
on transport errors.

ARM64 GCC 16.2.1 passed 25 cases at each of 4 KiB and 64 KiB page sizes with
`-O2 -flto -Wall -Wextra -Werror -fsanitize=undefined
-fsanitize-undefined-trap-on-error`. Cases include plain and patched success,
four auxiliary buffers, partial-copy failures, physical-address failures,
SCM errors, copy-back mapping failure and failures before allocation. The
unpatched `.10` body is rejected at free. Removing the wipe or clearing only
`need` bytes is also rejected at both page sizes. Strict checkpatch reports
zero errors, warnings or checks.

Evidence is in [validation/invoke-wipe.json](validation/invoke-wipe.json),
[validation/baseline-unwiped.json](validation/baseline-unwiped.json),
[validation/checkpatch.txt](validation/checkpatch.txt), and
[source-status.json](source-status.json). These are synthetic control-flow and
buffer-content tests, not DMA/cache-coherency, concurrency, full-kernel or
hardware validation. The `.11` release includes this patch and must replace the
older kernel before credentials are sent through the transport.

To repeat inside the ARM64 build container, bind the patched source read-only
at `/kernel` and this directory at `/tests`, then run:

```sh
python3 /tests/test-invoke-wipe.py /kernel
```

Use `--expect-unwiped` only against the unpatched `.10` source to reproduce
the expected failure; that option does not make the old kernel acceptable.
