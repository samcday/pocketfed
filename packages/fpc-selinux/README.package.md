# Inactive FPC policy modules

This package supplies `pocketfed_fpc.pp` and `pocketfed_fpc_broker.pp` under
`/usr/share/selinux/packages/targeted`. Installing it does not activate policy,
relabel paths, enable services or create credentials.

The module permits the existing confined fprintd domain to access the native
FPC control device, public TEE devices 0–15 and the enrollment-broker socket.
The broker's private credential directory has a separate type; fprintd does
not receive permission to read or modify its files. The supplementary broker
module labels the exact native broker executable and gives it a dedicated
confined domain, allowing fprintd to connect to that peer. It adds no connection
permission to generic unconfined services. See `README.broker.md` for the live
denial that motivated this correction and the remaining runtime validation.

An image builder must integrate both modules with a complete distribution policy
store and verify that unrelated policy and file contexts are preserved. A
compiled policy alone is insufficient for rebuilding an empty module store.
The final enforcing policy, process and object labels, service restrictions
and actual device operations require runtime verification before claiming
enrollment or authentication support.

These modules contain no firmware, credentials or biometric templates.
