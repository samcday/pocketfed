# Premouth Fedora packaging

RPM packaging for the validated Rust Premouth 0.1.0 boot animation. The
package installs a native ELF binary under `/usr/libexec/premouth`, built
from locked, deterministic, allowlisted source and vendor archives.
Runtime dependencies are ordinary shared libraries installed into the
initramfs by dracut's `inst_binary`; no prebuilt static binary is shipped.

## Building

```console
$ python3 packages/premouth/prepare-srpm.py --output /tmp/premouth-rpmbuild --offline
$ rpmbuild --define '_topdir /tmp/premouth-rpmbuild' -ba /tmp/premouth-rpmbuild/SPECS/premouth.spec
$ copr-cli build --chroot fedora-rawhide-aarch64 --chroot fedora-rawhide-x86_64 samcday/pocketfed /tmp/premouth-rpmbuild/SRPMS/premouth-*.src.rpm
```

The prepare step runs offline and records provenance (git revision plus
scoped dirty input hashes) while preserving vendored licenses. The commands
above prepare and submit builds; they do not claim a build has been
published.

## Testing

`test-notify.py` is the `%check` acceptance probe. It drives a real Unix
datagram `NOTIFY_SOCKET` against a synthetic device tree, with no display
hardware, no root privileges and no service manager:

```console
$ python3 packages/premouth/test-notify.py /usr/libexec/premouth
```

Pass the premouth binary as the first argument, or set `PREMOUTH_BINARY`.
Each case is bounded by a five second subprocess timeout.

## Integration

The PocketFed base image includes the package; a Sargo-only policy adds the
dracut module. There is no global activation and no RPM scriptlet. The
five second animation yields early and never delays Plymouth, and optional
runtime errors fail open. Add `rd.premouth=0` to the kernel command line to
disable the service on the next boot.

Runtime counters land in `/run/premouth/stats.txt`; service logs are
available via `journalctl -b -u premouth.service`. The test-sargo prototype
passed capture, full visual review and early preemption; acceptance of the
installed RPM is still pending and is not claimed here. See the
[premouth tooling documentation](../../tools/premouth/README.md) for
service, statistics and development details.

## Licensing

Premouth sources are `MIT OR Apache-2.0`; `tools/premouth/LICENSE-MIT`
carries the MIT text and vendored licenses are preserved in the source RPM.

The drm-fourcc 2.2.0 crates.io archive omitted the MIT license text, so
`packages/premouth/drm-fourcc-LICENSE` supplements it with the authentic
upstream LICENSE from
<https://github.com/dzfranklin/drm-fourcc-rs/blob/bb1b81f184650e1418e1dce512e34071675206d7/LICENSE>.
It is preserved with the vendor notices without changing vendored code.
Public RPM acceptance has not been completed.
