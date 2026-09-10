# Phosh rejected-PIN retry fix

Phosh 0.57.0 answers every PAM password prompt with the PIN collected by the
lockscreen. After a wrong PIN, `pam_systemd_home` emits `PAM_ERROR_MSG` and asks
again. Phosh supplies the same rejected PIN four times within one visible
attempt. This repeats homed's verification delay and consumes its rate limit.

The patch remembers an error reported after supplying a token and refuses
subsequent prompts with `PAM_CONV_ERR`. PAM messages receive empty responses;
errors before the first token and repeated prompts without an intervening error
remain supported. Each submitted PIN owns a separate PAM transaction, finished
before its conversation state or token goes out of scope. No public API changes.

This fixes credential replay. It does not change homed's remaining failure delay,
PAM's configured faildelay, the PIN hashing cost or rate-limit policy. It also
does not implement an interactive conversation or support a module that needs
another kind of secret after the submitted PIN.

## Fedora packaging provenance

The fork starts at Fedora dist-git
[`2af913d673c777a18280dbc6ff97415b5dfb8078`](https://src.fedoraproject.org/rpms/phosh/c/2af913d673c777a18280dbc6ff97415b5dfb8078),
Phosh `0.57.0-1`. PocketFed uses `0.57.0-1.1.pocketfed`, which upgrades release 1
while allowing Fedora release 2 to supersede it. The spec retains Fedora's
dependencies, subpackages, build options, PAM service and full enabled test
suite. The image already replaces Fedora's direct-pam_unix service with the
authselect stack that supports homed.

Changes are the source patch, Fedora lookaside download URLs, explicit release,
expanded Fedora changelog and
`phosh-pam-retry-fix = 1` capability. `%check` requires the new regression binary
to exist and executes it through the existing Meson test suite. The unmodified
Fedora `sources`, `changelog` and PAM file are retained. All three source archives
were verified against Fedora's SHA-512 lookaside record; `sources.sha256` records
the same bytes for the common COPR source build helper. Archives and RPMs are
kept outside Git. The source URLs use these checksum-addressed Fedora copies
because GNOME GitLab returned HTTP 503 during COPR source preparation.

## Validation

`tests/test-auth.c` in the patch compiles the actual `src/auth.c` against synthetic
PAM functions. It exercises the public asynchronous authentication API without
using real credentials, the host PAM stack or a privileged service. Seven cases
cover homed-like retries, fresh input after failure on the same object, early
error/information messages, multiple prompts without rejection, multi-message
rejection, unknown message styles, account failure and PAM-start failure.

Run the patched suite and the original-source negative control with a compiler,
Python 3, patch, PAM headers and GLib/GIO development files:

```sh
python3 packages/phosh/test-auth.py /path/to/phosh-v0.57.0.tar.gz
```

The patched suite must pass all seven cases. The unmodified release must fail
the homed regression specifically with four password checks instead of one.
This models homed's conversation; it is not a measurement of live phone unlock
latency. A device acceptance check should compare the journal's AcquireHome
calls for one deliberately wrong PIN, then verify a normal correct unlock.

## Build

Use the repository's `.copr/Makefile` with SCM subdirectory `packages/phosh`,
method `make_srpm`, and a pinned Git commit. Build for `fedora-rawhide-aarch64`
and `fedora-rawhide-x86_64`; this Fedora 46 package is not built for Fedora 45.

For a local SRPM, from this directory:

```sh
spectool -g phosh.spec
sha256sum --check sources.sha256
rpmbuild -bs --define "_sourcedir $PWD" --define "_srcrpmdir $PWD" \
  --define 'dist .fc46' --define 'fedora 46' phosh.spec
```

The image pins matching Phosh/libphosh builds and checks the fix capability.
Retire the fork and image pin together once Fedora carries a validated fix.
