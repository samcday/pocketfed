# Enrollment broker peer domain

The enforcing `fprintd-libdir` trial reached real enrollment but failed before
broker activation: `fprintd_t` was denied `connectto` to
`unconfined_service_t` at `/run/pocketfed-fpc-auth/token.sock`.

The earlier PID1 socket-label prediction was incorrect. In the local systemd
source, `socket_determine_selinux_label()` asks
`service_determine_exec_selinux_label()` for the service's execution label.
PID1 creating the listener does not make its peer SID `init_t`.

This supplementary candidate labels only `/usr/bin/pocketfed-fpc-auth` and
transitions that executable from PID1 into a dedicated confined domain.
Systemd can then create the activation socket with that domain. The new fprintd
permission targets only this peer; generic unconfined-service access remains
forbidden, as do reads of service credential files. Existing root ownership,
socket framing, peer checks and systemd restrictions remain necessary.

The broker domain permits its libc runtime, inherited standard descriptors,
its existing private state namespace, and public TEE client ioctls. It has no
unconfined attributes, private TEE/RPMB device access, network permission or
subprocess execution grant. It does not create a credential or grant fprintd
the broker's state permissions. Runtime validation is pending.


`prepare-policy.py` compiles this module into a copy of the exact trial policy,
verifies the unchanged policy outside the two new types, and checks positive
and negative permissions plus executable labels using SETools and libselinux.
It never loads host policy. `trial-build.json` records the tested source and
policy/context hashes. The enforcing `fprintd-peer` run permitted the socket
connection but failed before broker execution: PID1 lacked `execute` access to
the new executable type. No RPMB callbacks occurred, and the trial shut down
cleanly before reset. The corrected candidate grants PID1 open/read/execute
access to that exact type and asserts both launcher and broker entrypoint
permissions offline. The next trial explicitly starts the broker and checks a
rejected invalid-version request before waiting for Volume Up. Broker execution
and authorization remain pending hardware validation.

The local noarch RPM and SRPM are recorded in `package-build.json`. Its payload
contains both inactive modules and documentation only, with no scriptlets.
The broker module bytes equal the offline-tested candidate. Normal image
integration must still preserve the complete distribution policy and context
store; installation of this data-only package does not activate it.
