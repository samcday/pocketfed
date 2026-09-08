# Flatpak portal startup fix

PocketFed forks Fedora's Flatpak packaging to fix Chromium waiting indefinitely
for a nested sandbox's `SpawnStarted` notification. The portal can receive the
instance ID before `flatpak run` writes its PID file; Flatpak 1.19.0 treats that
temporary absence as a permanent construction failure and loses the notification.
The correction retries construction using the existing asynchronous metadata
timer. It preserves invalid-PID rejection and stops tracking exited processes.

The investigation and upstream follow-through are tracked in
[PocketFed issue #35](https://github.com/samcday/pocketfed/issues/35).
The [report, patch attribution and phone validation](../../docs/upstream/flatpak/)
describe the earlier temporary portal trial. This package delivers the same
portal correction through the normal COPR/image update path.

## Fedora packaging provenance

The packaging base is Fedora Rawhide dist-git commit
[`44da60affc6b697a0899305844e501e60ef5b66d`](https://src.fedoraproject.org/rpms/flatpak/c/44da60affc6b697a0899305844e501e60ef5b66d),
whose generated release is Flatpak `1.19.0-3`. PocketFed uses
`1.19.0-3.1.pocketfed` so it upgrades Fedora's release 3 while a later Fedora
release 4 can supersede it. Fedora's build options, dependencies, subpackages,
service integration and installed tests are retained. Its `fd-conflation.patch`,
`eagain.patch` and service-file permissions correction are preserved.

The downstream changes are the PID retry patch, explicit release and expanded
Fedora changelog, and the production-source regression check in `%check`.
Fedora's base spec has no `%check` section; this fork does not remove or disable
an existing upstream test invocation.

The checked-in `sources` file is Fedora's unmodified lookaside record. The
source archive's SHA-512 was verified against it:

```
686b6152705e6168d74093d44370d308093fa98d6c4e693f00804e540ee8f135b5994efa72f783a081b98d9c1b41ecdb4664f4fe05c78418cb5c6fbc5691f501
```

`sources.sha256` records the same archive for the common
[COPR SRPM helper](../../.copr/Makefile). Archives and RPMs remain outside Git.
The retry patch is byte-identical to the previously tested phone correction,
with SHA-256 `6b3995b40c3993d084444dcae642111aa79f6c8d1321059b00b7d50d9f1e0abe`.

## Regression check

The `%check` command compiles the actual `get_pid()` implementation and complete
startup callbacks from the source tree prepared by the RPM's `%prep`. Real
temporary files and GLib asynchronous callbacks exercise ready metadata,
delayed child metadata, delayed PID publication, three process-exit timings,
invalid PIDs and permanent file errors. Metadata plumbing and D-Bus signal
delivery are test doubles; this is a focused source regression check rather
than a full desktop session integration test.

The unchanged release archive supplies the negative control. It must fail the
same required delayed-PID notification assertion that the prepared source
passes. Because the candidate is read directly from the prepared source tree,
the check also fails if the RPM stops applying the retry patch.

Run it manually after `%prep` with a compiler, Python 3 and GLib/GIO development
files installed:

```sh
python3 packages/flatpak/test-start-notification.py /path/to/flatpak-1.19.0.tar.xz \
  --prepared-source /path/to/flatpak-1.19.0
```

## Build

Use the repository's common `make_srpm` flow with package subdirectory
`packages/flatpak`, or prepare an uploaded SRPM from this directory:

```sh
spectool -g flatpak.spec
sha256sum --check sources.sha256
rpmbuild -bs --define "_sourcedir $PWD" --define "_srcrpmdir $PWD" \
  --define 'dist .fc46' --define 'fedora 46' flatpak.spec
```

The permanent acceptance check is a reboot into an image containing this RPM,
followed by a normal Chromium launch using the packaged `/usr/libexec/flatpak-portal`.
The earlier `/run/user/1000` portal trial disappears at reboot.

When Fedora carries a validated correction, retire this downstream fork and its
image package pin together.
