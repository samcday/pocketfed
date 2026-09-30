# Offline SELinux integration review

Runtime correction, 12 September: the activation socket's peer SID is derived
from the service executable. The live `fprintd-libdir` trial observed
`unconfined_service_t`, contrary to the PID1 peer prediction in this historical
review. A supplementary [dedicated broker domain](../fpc-selinux/broker/README.md)
is being prepared; the original object-label module alone is insufficient.

The fingerprint trial needs additional SELinux integration before its confined
`fprintd` can open the new sensor and TEE devices. The systemd `DeviceAllow=`
additions do not grant SELinux access. No SELinux policy changes, live device
operations, or authentication attempts were performed for this review.

## Exact evidence and limits

This review used the compiled policy and file-context database extracted from
local ARM64 image
`d00f4e30950d566d2bb5181343d61836bf95e9d04f99cfb0a4c604def65889db`.
That image is the rejected earlier candidate with the known Phosh PAM
regression; these results do not validate or approve that image. Its
`policy/policy.35` SHA-256 is
`ca98dfcea858d4974bdaa1e10e54e1d70264a28c0fb79c03e339565360384973`.
The policy was read with host SETools; contexts were resolved using
`matchpathcon -n -N -m TYPE -f IMAGE_FILE_CONTEXTS PATH`, including the image's
local and substitution context files. Extraction used a read-only, networkless
container. The policy and context evidence remains under
`/tmp/fpc-selinux-audit`; the compact query results are also recorded in
`validation/selinux-policy.json`.

The coordinator's separate read-only phone inspection found SELinux enforcing,
`selinux-policy-targeted-45.15-2.fc46`, and `systemd-262~rc1-6.fc46`. The
conclusions below are predictions for the image's default labels and service
transitions, not observations of the phone's process or inode labels. A matching
RPM version does not prove that the running policy, local modules, booleans, or
persistent inode labels match this image. In particular, `/dev/tee*` and
`/dev/fpc1020` were absent from the earlier running kernel. Runtime evidence is
still needed after an authorized trial boot.

## Expected domains and access

| Object or executable | Image default type | Compiled-policy result |
| --- | --- | --- |
| `/usr/libexec/fprintd` | `fprintd_exec_t` | `init_t` execution transitions to `fprintd_t`, which is not permissive. |
| `/dev/tee0` through `/dev/tee15`, `/dev/teepriv0`, `/dev/fpc1020` | `device_t` | **No `fprintd_t` character-device `open`, `read`, `write`, `getattr`, or `ioctl` allowance.** |
| `/var/lib/fprint/fpc-qsee` and its files | `fprintd_var_lib_t` | The expected state-directory, lock, and file operations are allowed to `fprintd_t`. |
| `/var/lib/qsee-supplicant` | `var_lib_t` | Directory `open`, `getattr`, `read`, and `search` are allowed to `fprintd_t`, sufficient for the current driver's directory metadata check. File-content reads are not allowed, but the current driver does not need them. |
| `/usr/bin/qsee-supplicant`, `/usr/bin/qsee-app-loader` | `bin_t` | Ordinary system-service execution transitions to `unconfined_service_t`; that domain has device and generic state-file access. |
| `/usr/libexec/phosh-fingerprint-worker` | `bin_t` | Ordinary system-service execution also transitions to `unconfined_service_t`; no dedicated Phosh worker domain exists in this policy. |
| Future `/usr/bin/pocketfed-fpc-auth` | `bin_t` | The same generic service transition is expected. The operational `0.2` package is absent from the reviewed image. |
| Future `/run/pocketfed-fpc-auth/token.sock` | `var_run_t` | **No `fprintd_t` `sock_file` access**, so the expected socket-path connection permission is missing. There is no actual broker socket in this image. |

The image contains only the existing `fprintd_*` fingerprint types; no dedicated
QSEE, FPC, or Phosh helper types were found. `NoNewPrivileges=yes` is not itself
an obstacle to the expected service transitions: the policy explicitly allows
`init_t` the `process2 nnp_transition` permission into both `fprintd_t` and
`unconfined_service_t`. None of the reviewed service units specifies
`SELinuxContext=`.

The only generic rule returned for `fprintd_t -> device_t:chr_file` is
conditional `map`, controlled by the default-disabled `domain_can_mmap_files`
boolean. Enabling that boolean would not grant the missing device operations.
No relevant `allowxperm` rule was returned. The default `sysfs_t` directory and
file reads used for device identity are allowed; actual sysfs labels still need
confirmation.

For the future broker, distinguish the pathname inode from the socket object's
peer SID. Its socket unit creates the listener in systemd and passes the
descriptor to the service. The policy allows `fprintd_t` a Unix stream
`connectto` to `init_t`, but not to `unconfined_service_t`. An activated socket
therefore cannot be diagnosed from the daemon's process label alone. The missing
generic `var_run_t:sock_file` permission remains a separate predicted failure.
The broker's root ownership, `0600` socket, `0700` directory and `SO_PEERCRED`
checks do not replace SELinux mediation.

The qsee-supplicant's expected `unconfined_service_t` domain means this image
provides no purpose-specific SELinux confinement for its secure-storage service.
That is separate from the concrete fprintd device-access blocker. Existing
systemd restrictions and application validation still apply.

## Subsequent candidate and store work

The separate module in `../fpc-selinux` now supplies exact device labels, a broker
socket type and a private credential-state type. Offline queries allow fprintd
to use the socket but deny credential file access, including conditional
branches. No new process transition or activation-peer grant is needed.

Read-only device inspection found that its persistent policy hash matches the
audited image, but `semodule -lfull` reports no modules. The signed Fedora policy
and active image additions have now been reconstructed offline; their decompiled
policy matches the image exactly after preserving its boolean setting. Its existing context files are now preserved as well; complete policy/context
preservation and device/socket access checks pass after normal module insertion. This does not
change the default-label findings above or prove running-kernel policy equality.
See `../fpc-selinux/distribution-investigation.json` and its README for evidence.

## Minimal controlled runtime confirmation

After the coordinator authorizes a trial boot and one normal activation, retain
enforcement and first collect only process labels, relevant path labels, unit
results, and a narrow time window of AVC records. Do not collect credential or
template contents. The useful checks are:

1. Record the active policy hash, enforcing state, and `ps -eZ` entries for
   systemd, fprintd, qsee-supplicant, the loader and Phosh worker. Inspect labels
   with `ls -ldZ` on the exact existing device nodes, state directories and
   socket paths. Compare each with `matchpathcon`; persistent `/var` labels can
   differ from the image defaults. Do not relabel anything during collection.
2. Bracket a single already-authorized activation/operation with timestamps.
   Save its unit journal and `ausearch -m AVC,USER_AVC` for that short interval;
   kernel journal AVCs are a fallback if audit records are unavailable. Preserve
   source/target contexts, object class, denied permissions, executable, path,
   and any ioctl value. Absence of an AVC alone does not prove access succeeded.
3. Correlate the first denial with the actual labeled object. Only then design
   explicit device/path labeling and narrowly scoped service policy, checking
   TEE shared-memory and ioctl behavior in the same controlled operation. This
   review does not propose broad access to `device_t`, generated `audit2allow`
   rules, policy booleans, permissive domains, or disabled enforcement.

The corrected image must have its policy hash and contexts compared again;
fixing its Phosh RPM alone does not resolve the device-access issue above.
