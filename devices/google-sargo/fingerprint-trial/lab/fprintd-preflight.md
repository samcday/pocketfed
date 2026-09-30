# fprintd enrollment/cancellation preflight

The [post-reboot authorization check](authorization.md) passed using the retained
lab credential and genuine FPC challenge. This next disposable trial uses the
actual cached-image packages: fprintd 1.94.5-6.fc45, libfprint
1.94.100-1.3.pocketfed.fc46 and native broker 0.1.0-0.2.pocketfed.fc46.
It remaps their service prerequisites to the proven lab receiver and loaders.
The native broker socket keeps its root peer and private state protections.

Run `sargo-fingerprint-lab-fprintd-preflight-20260911` is restricted to handset
`99NAY1AZG1` and restores only the retained native lab credential. The ephemeral
`fprintlab` account has UID 1234 and a nologin shell. Its fresh QSEE namespace is
required to be empty before the explicitly marked first fingerprint database
initialization. No daily-phone credential or fingerprint database is copied.
The receiver retains the eight-group authenticated-write cap and write-error
latch, with no key programming or automatic credential enrollment.

One D-Bus connection claims the sensor, subscribes to enrollment status, starts
right-index enrollment, then cancels after six seconds. Any completed result
before that cancellation is recorded as an unexpected outcome. It releases
the sensor, claims it again to reload the database, checks that fprintd lists
no enrolled fingers, and releases it. The completed Gatekeeper record must be
unchanged. Successful completion stops fprintd, the broker/socket and secure
services in order. The controller makes no second enrollment request.

The generated private root and source/binary identities are recorded in
[fprintd-preflight-build.json](fprintd-preflight-build.json). ARM64 receiver tests
passed, and its sole change from the successful authorization run is the exact
run token.

The first boot passed enforcing handoff and secure-service startup, then stopped
when the native broker socket remained masked. Removing a symlink from the
additive overlay had not removed the same mask from the base image. There was
no D-Bus enrollment request or RPMB callback. The failed report and consumed
launch receipt were preserved; the handset returned to fastboot before hosting
stopped. This failed run did not test orderly secure-service shutdown.

`lab_fprintd_unmasked.py` prepares a separate run and requires that prior failure
evidence. After exact serial/run validation, its controller explicitly unmasks
only fprintd and the native broker service/socket in the disposable runtime,
reloads systemd and requires all three units to be loaded. The original artifacts
remain unchanged. It also records failed systemctl diagnostics and socket logs.
The corrected test is being prepared; actual finger enrollment, positive/negative
matching, persistence and desktop login remain separate acceptance work.

That run successfully started the broker socket, then exposed a second fixture
issue: systemd dependency lists cannot be cleared through empty settings in a
later drop-in. The packaged `90-fpc-qsee.conf` still required the masked
production receiver. `lab_fprintd_dependencies.py` replaces that exact filename
under `/etc`, preserving its device permissions and substituting only the lab
services. It verifies the effective `Requires` set before activation.

The dependency-corrected run **passed**: fprintd started, Claim/EnrollStart/
EnrollStop/Release returned successfully, and a fresh Claim reopened the 77-byte
empty database. No enrolled fingers remained and the native credential was
unchanged. All services stopped cleanly; enforcing handoff and reset-to-fastboot
also passed. [fprintd-dependencies-result.json](fprintd-dependencies-result.json)
records that evidence. There was no RPMB callback or observed token-broker
activation during this short cancellation trial, so it does not by itself prove
that a broker token was requested through fprintd. Real enrollment and matching
remain the next checks. Sam has confirmed availability for finger touches.
