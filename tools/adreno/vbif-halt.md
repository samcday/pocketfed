# A306 ordinary runtime suspend: VBIF halt mask

A clean stock DB410c boot (B10) separates this failure from the recovery clock
leak: no GPU hang or recovery preceded either measurement. After stopping
`phrog.service`, no DRM clients or phoc/greetd processes remained. GPU runtime
status nevertheless stayed active with zero accumulated suspended time.

## Localizing the failed check

A scoped instance recorded these five returns in t20:

```text
r64:GROUP/idle_ring msm:adreno_idle ret=$retval:u8
r64:GROUP/idle_gpu msm:a3xx_idle.part.0 ret=$retval:u8
r64:GROUP/suspend_a3xx msm:a3xx_pm_suspend ret=$retval:s32
r64:GROUP/suspend_generic msm:msm_gpu_pm_suspend ret=$retval:s32
r64:GROUP/resume_generic msm:msm_gpu_pm_resume ret=$retval:s32
```

Changing `/sys/bus/platform/devices/1c00000.gpu/power/control` from `on` to
`auto` triggered the attempt. Both idle functions returned 1 at 279.610 s;
A3xx suspend returned -16 at 280.609 s. Generic suspend/resume had no hits.
This localizes the failure to the intervening VBIF halt poll. Stopping the
service alone had produced no callback inside this capture.

## Reading the request before cleanup

The shipped Fedora module is tied to
`7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46.aarch64`. Its raw ELF SHA-256 is
`832fff363ccb21890c8c3bdf6e63062530090f5cb38cf9b7b53f840eeb61ed93`;
live `.note.gnu.build-id` SHA-256 is
`d0c1a71c7555e24ea32914c70cd8fd654bb35bf4141b63eae9a657d98cf19091`.

Disassembly shows the compiler inlines `a3xx_vbif_halt()` inside
`a3xx_pm_suspend()`. It writes `0x3f` to MMIO byte offset `0xc200`, then polls
`(read32(0xc204) & 0x3f) == 0x3f`. At function offset `+0xb4`, before clearing
the request, x19 contains the signed poll result and x22 the `msm_gpu` pointer;
the MMIO pointer is at structure offset `0xc8`. The stock-only probe is:

```text
p:GROUP/preclear msm:a3xx_pm_suspend+0xb4 poll_ret=%x19:s32 request=+0xc200(+0xc8(%x22)):x32 ack=+0xc204(+0xc8(%x22)):x32
```

The two register fetches are aligned 32-bit reads while the device is active.
They do not write registers or change the mask. At 539.656022 s, t21 records
`poll_ret=-110 request=0x7 ack=0x70007`; the next outer return is -16 to
`adreno_runtime_suspend+0x44`. The implemented low three bits have acknowledged,
but the six-bit condition cannot succeed.

The [helper](trace-vbif-halt.sh) refuses any different loaded-note hash before
registering this instruction-specific probe. It creates its own instance and
event group, records return values/hit counts/buffer statistics, and cleans up
only its own tracing resources. It starts no workload and changes no power
policy. Syntax, ShellCheck and probe-generation checks pass; t21 validates
registration, recording and cleanup on the exact stock binary. Both t20/t21
have zero missed probes and zero per-CPU overruns/dropped events. Archive
hashes and the restored display-service state are in the
[hardware ledger](hardware-20260923.md#b10-clean-stock-idle-failure-and-a306-halt-mask-mismatch).

## Independent source and candidate

Qualcomm's downstream [A3xx setup](https://android.googlesource.com/kernel/msm/+/c90c7feeca2f5839ad6824f816c0bd207602a2f4/drivers/gpu/msm/adreno_a3xx.c#633)
selects `A30X_VBIF_XIN_HALT_CTRL0_MASK` for A306, A306A and A304. Its matching
[register header](https://android.googlesource.com/kernel/msm/+/c90c7feeca2f5839ad6824f816c0bd207602a2f4/drivers/gpu/msm/a3xx_reg.h#482)
defines that mask as `0x7` and the generic A3xx mask as `0x3f`, with the same
`0x3080/0x3081` register offsets in DWORD units. This corroborates the A306
hardware observation. Those other variants have not been measured here.

[Linux PR #6](https://github.com/samcday/linux/pull/6) initially changes only
A306 to `GENMASK(2, 0)`, using the existing helper for revision 307 (revision
306 denotes A305c). Other A3xx GPUs keep the existing mask. Review can address
whether the downstream-supported variants should be included too.

The mask-only module builds with the matching Fedora ARM64 compiler and exact
kernel-devel configuration/symbols. All 784 imports, ten dependencies and
vermagic match stock; strict checkpatch passes. Disassembly selects `0x7` only
for revision 307, uses it for request/poll, and retains stock recovery code.
The candidate is unsigned, external and lacks module BTF, as with PR #5.

- ELF build ID: `2a9ead12954b47e1f50d4b8a546dbb0dfe55c740`
- Raw module SHA-256: `174726a7ff6a8a5b9d2446ed8cbd7891a71465f923ec88458269ac8c6c1dfb69`
- CRC32-XZ SHA-256: `ab7375c3aec783644278db12015f00f6e3da5ccf735049de0213a3ed7cb57e40`
- Expected live note SHA-256: `0899f3b83153e90ab5151e168cea240184e8c6e3096b82a5da8cdeafdce5d1eb`

The separate temporary boot changes only that initramfs module and a boot
marker, preserving the kernel Image, DTB, all other 730 CPIO entries and the
same immutable root/export. Fresh mask-only runtime-PM testing is in progress;
a successful build is not a successful suspend/resume cycle. The original Mesa
hang and [recovery correction](recovery-clocks.md) remain separate concerns.
