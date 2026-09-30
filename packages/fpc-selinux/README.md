# FPC/QSEE and enrollment-broker SELinux policy — offline candidate

# Runtime correction, 12 September 2026

The `fprintd-libdir` live trial disproved the PID1 activation-peer prediction
below. systemd labels the activation socket for the service executable; the
actual denial was `fprintd_t -> unconfined_service_t:unix_stream_socket connectto`.
The supplementary [broker domain](broker/README.md) is being tested with a
dedicated confined peer. The historical offline checks below establish the
base module's device and pathname permissions, not a working broker connection.

This candidate lets the existing confined `fprintd_t` domain access Sargo's FPC
and public TEE devices and the enrollment-broker socket. Separate labels keep
the broker credential files inaccessible to fprintd. It has not been loaded or
exercised on the phone and is absent from image `83cc5287c9ae`.

The RPM contains only the compiled module and documentation; installation does
not register or load policy, relabel files, enable services, or create state.
The phone and image have an empty module store despite an existing compiled
policy. Do not run `semodule -i` against that empty store. Image integration must
first reconstruct and verify its distribution policy and preserve existing
file contexts. That work is recorded in `distribution-investigation.json`.

[COPR 10973947](https://copr.fedorainfracloud.org/coprs/build/10973947) succeeded.
The source and noarch RPM signatures are verified; the packaged module is
byte-identical to the module used in the offline tests. RPM inspection confirms
that it has no scriptlets and contains only the module and documentation.
See `build.json` for exact source/artifact hashes. `prepare-srpm.py` snapshots an
explicit list of public module sources and generic package instructions; live
inspection records are not part of the package.

The source is deliberately small:

- `pocketfed_fpc.te` adds two `device_node` types and grants the required device
  access from `fprintd_t`. Two other types label the private broker state and
  runtime socket directory. No service domain or transition is changed.
- `pocketfed_fpc.fc` labels only character devices `/dev/fpc1020` and
  `/dev/tee0` through `/dev/tee15`. It does not match `teepriv`, leading-zero
  device names, a larger index, another inode class, or descendants. It also
  labels `/var/lib/pocketfed-fpc-auth`, its private contents, the broker runtime
  directory, and the exact `token.sock` socket path.
- `test-policy.py` compiles the module and package, combines it with an offline
  image policy, and queries the result. It does not open a policy store, load
  policy, write labels or access devices. It can also query an externally
  rebuilt policy and context database using `--merged-policy` and
  `--merged-contexts`. The normal build only compiles the module.

## Exact permission justification

Both clients open their device with `O_RDWR`, so SELinux needs `open`, `read`
and `write` even though neither code path calls `write()` on the device.
`getattr` supports device discovery; the sensor reads its 16-byte IRQ events.
`ioctl` is constrained with extended permissions to the current UAPI commands:

| Type | Allowed ioctl low 16 bits | Current call sites |
| --- | --- | --- |
| `pocketfed_fpc_device_t` | `0x4600`, `0x4601`, `0x4602` | `packages/fpc-qsee/sensor.c`: reset, wake enable/disable, IRQ snapshot. |
| `pocketfed_fpc_tee_device_t` | `0xa400`, `0xa401`, `0xa402`, `0xa403`, `0xa405` | `packages/fpc-qsee/qsee-transport.c`: version, shared-memory allocation, open session, invoke, close session. |

SELinux's ioctl hook uses the low 16 bits, which identify the ioctl family and
number; the kernel retains validation of direction, size and contents. Unused
TEE cancellation, shared-memory registration, object invocation and privileged
supplicant commands are excluded. Adding a new transport operation requires
reviewing this list. The transport currently discovers a wider glob before
checking the TEE implementation; this candidate intentionally only permits the
same 16 public device paths allowed by the fprintd systemd drop-in.

The kernel's current FPC driver has no raw SPI transfer operation. Device access
does not produce a biometric match: authentication remains in the existing
trusted-application protocol and libfprint/fprintd path.

There is no `map` permission on either character device. The transport calls
`mmap(PROT_READ | PROT_WRITE, MAP_SHARED)` on the separate descriptor returned by
`TEE_IOC_SHM_ALLOC`, then closes that descriptor. In the reviewed `.10` kernel:

- `drivers/tee/tee_shm.c:tee_shm_get_fd()` uses `anon_inode_getfd("tee_shm", ...)`.
- `fs/anon_inodes.c` uses the shared anonymous inode for this API; `fs/libfs.c`
  marks that inode `S_PRIVATE`.
- `security/selinux/hooks.c:inode_has_perm()` returns without an inode-policy
  check for `IS_PRIVATE` inodes. The mapping's remaining file access check uses
  that same helper. These are non-executable mappings created and used by the
  same process, so no additional cross-domain descriptor or `execmem` grant is
  justified by this path.

This is source evidence, not a successful live mapping. If the kernel changes
to a separately labeled anonymous inode, or actual AVCs identify another
shared-memory object, evaluate that object's label and operation separately.
Do not respond by allowing `map` on all devices or anonymous inodes. The
candidate adds no such rule.

The socket inode receives `pocketfed_fpc_auth_run_t`; fprintd gets directory
search and socket `getattr`/`write`. That does not grant access to the activation
socket's peer SID, which systemd derives from the service executable. The live
trial found the generic `unconfined_service_t` peer and a connection denial.
The supplementary [broker policy](broker/README.md) supplies a dedicated peer;
the original object-label module alone does not make enrollment work.

Credential files receive `pocketfed_fpc_auth_state_t`, rather than fprintd's
existing state type. The module grants PID1 the directory creation/attribute
operations needed for `StateDirectory`. Tests query all conditional branches
and reject fprintd access to credential file contents or modification. Existing
fprintd state labels and qsee-supplicant directory metadata access are unchanged.
These are policy predictions; actual process and object labels remain untested.

## Offline validation

The test requires Python SETools, libsepol, checkpolicy, checkmodule,
semodule_package, the SELinux PP-to-CIL helper, and matchpathcon. On the reviewed
host those are available through `/usr/bin/python3` and `/usr` tool paths.

```sh
make -C packages/fpc-selinux check \
  POLICY=/tmp/fpc-selinux-audit/image-policy/policy/policy.35 \
  CONTEXTS=/tmp/fpc-selinux-audit/image-policy/contexts/files/file_contexts \
  REPORT=/tmp/fpc-selinux-audit/candidate-validation.json
```

Tests passed against the rejected earlier `d00f4e3` image's exact policy, SHA-256
`ca98dfcea858d4974bdaa1e10e54e1d70264a28c0fb79c03e339565360384973`.
That test does not approve the rejected image or imply the corrected candidate
contains this policy. See `device-only-validation.json` for that historical two-type candidate and
`broker-policy-validation.json` for the extended four-type candidate.
`distribution-policy-validation.json` records queries against the separately
rebuilt module store, including its actual generated context database.

The harness converts the image binary policy to CIL and compiles it with the
candidate through libsepol's public CIL API. It supplies the normal
`cil_gen_require` module bookkeeping attribute, which the binary policy omits.
This proves symbol, class and permission compatibility and allows querying the
combined policy. A compiled binary lacks the distribution source's
`neverallow` assertions; this test therefore does not validate those assertions
or replace a future offline build against the distribution module store.

The generated module must first match the complete reviewed declaration, rule
and file-context contract. This rejects unrelated grants to pre-existing types,
extra conditions, attributes, transitions or permissive flags before the merge.
The queries then require exact added types and permissions, exact ioctl sets,
unchanged generic device/runtime-object and activation-peer rules, unchanged process transitions and
nonpermissive fprintd. The real libselinux path matcher tests all 17 positive
character-device names and rejects privileged, out-of-range, leading-zero,
similar-prefix, descendant and wrong-inode-class matches.

Independent review found no unintended grant in the candidate, but identified
that the initial target-limited query tests accepted an unrelated
`fprintd_t -> etc_t:file write` rule. After adding the complete module contract,
that synthetic mutation, an extra device `map` grant, a `teepriv0` context,
credential-file read access and a broader service-peer grant all fail before
the merge. `test-contract-regressions.py` and `contract-regressions.json`
record the five rejection cases.

## Required evidence before claiming runtime compatibility

The corrected image must retain the audited rules and existing context
behavior. The exact Fedora 45.15-2 policy package was retrieved from Koji's
signed directory and verified against the installed Fedora 46 primary key.
Reconstruction with the image's active package additions and `virt_use_nfs`
setting produces byte-identical decompiled CIL to the audited image policy.

The stock distribution store and stock plus fingerprint module both build with
`expand-check=1`. The existing container module causes 13 neverallow assertion
failures before fingerprint is added. The image's existing semanage config uses
`expand-check=0`; reconstructing that configuration does not establish that all
source assertions pass. Preserve and report this distinction.

File-context reconstruction is now verified separately. The initial rebuild
generated home paths from the build host's `/home` symlink and missed the image's
converted `/run/pasta.pid` entry. The corrected isolated store preserves the
exact existing home-context file with generation disabled in its temporary build
configuration and retains the existing runtime-path conversion module. The
reconstructed baseline's decompiled CIL and all existing context text files are
byte-identical to the audited image.

Adding the fingerprint module through normal `semodule -n` passed the access
and actual-context tests. `test-preservation.py` then removed only the explicitly
reviewed additions and required the remaining complete decompiled CIL byte
sequence to match the baseline, including conditional nesting. Five attribute
membership additions, the expected four types and rules, and exactly five new
context entries are the only changes. Every other context text file is
byte-identical. See `preservation-validation.json`.

A strict rebuild of both the reconstructed baseline and integrated store also
produced identical diagnostics for the same 13 pre-existing container assertion
failures. The fingerprint module adds none. The data-only package intentionally
has no installation scriptlet or policy-loading target. The verified store remains a temporary offline artifact. Image
`671197f9f3bf` now includes its exact compiled policy and contexts, with the
regex cache compiled using the ARM64 base. Complete image comparison and ARM64
context lookup passed. No policy has been loaded on the phone; enforcing runtime
checks remain.

During a separately authorized enforcing trial, verify that udev labels the
actual nodes with these types and that fprintd really runs in `fprintd_t`.
Collect the first normal operation's narrow-window AVC and unit journal output
as described in `../fpc-auth/selinux-integration.md`, including any shared-memory
or ioctl denial. Persistent state labels, device labels, DAC ownership, systemd
device controls, and firmware/TEE readiness remain separate runtime conditions.
Do not infer enrollment, verification, or Phosh/Phrog login success from this
offline policy result.
