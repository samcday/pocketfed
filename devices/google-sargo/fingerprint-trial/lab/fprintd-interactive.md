# Interactive fingerprint trial

The first touch-driven run booted the accepted enforcing USB root and started
fprintd successfully. Its initial identify-for-enrollment scan timed out after
30 seconds with `enroll-unknown-error`. Sam confirmed he was in another room and
did not touch the sensor during that window. This is not evidence of a capture
failure with a finger present.

The native token broker was not activated, there were no RPMB callbacks, and no
fingerprint was enrolled or exported. EnrollStop and Release returned. The trial
did not reach its orderly service shutdown; UART reset and the exact fastboot
serial were verified before stopping USB hosting. See
[the sanitized result](fprintd-interactive-result.json).

The second fixture added a 20-second lead-in and also timed out during the
initial identify scan. No broker activation, RPMB callback, enrollment or export
occurred. Sam later explained he stopped the session while watching football
and did not want to go to the other room for enrollment. Neither run proves a
capture failure with a finger present. See the
[countdown result](fprintd-countdown-result.json). Its enforcing handoff report
was recovered from UART audit interleaving; the runner's original state was
preserved. Reset and exact-serial fastboot return preceded host termination.

Sam requested device-side readiness on 12 September. The
[volume-button fixture](fprintd-buttons-build.json) uses `lab_fprintd_buttons.py`
for receiver preparation, fixture preparation, sealing, boot and private
collection. It displays instructions on VT1 and waits indefinitely for a fresh
Volume Up press/release before enrollment, matching and nonmatching. Volume Down
cancels a wait or requests Stop during an active scan. A held or repeated key
cannot advance the next stage; an input overrun fails rather than guessing.
Driver timeouts and duplicate checking remain unchanged, and start only after
the local readiness gate. A synchronous secure call still has to return before
normal cancellation/teardown can finish.

The sequence is right-index enrollment, private retention of the new lab
database and fprintd metadata, an enrolled-finger match, then a different-finger
rejection. New biometric records remain in the private local vault; result
summaries contain status and counts only. Each boot consumes its own launch
receipt. Earlier attempts and frozen sources remain available for review.

The new button sequence tests and real GLib integration tests cover readiness,
separate phase gates, held/repeated keys, input overrun, cancellation before a
start, and cancellation during a scan with exactly one Stop and Release.
An attempted clean service shutdown now also follows cancellation or a returned
error; teardown stops at the first service-stop failure.

The buttons fixture has now booted on the exact test handset. It discovered
`gpio-keys` and `pm8941_resin`, activated VT1, and successfully disabled console
blanking with setterm. Its initial waiting state remained unchanged for at least
67 seconds with no readiness press or enrollment start. The USB host was
confirmed live; see [the waiting checkpoint](fprintd-buttons-waiting.json).
Physical key activation, visible-screen usability, enrollment and matching still
need Sam's interaction. The enforcing handoff report again required recovery
from audit interleaving; the automatic runner state has not been rewritten.
Keep the host process and USB connection alive while this fixture waits.

Sam subsequently pressed Volume Up and the sensor captured a touch. The
initial identify returned command `-208`, before token-broker activation or
enrollment. All services stopped cleanly; the guest returned to the exact
fastboot serial before its host was stopped. See
[the completed buttons result](fprintd-buttons-result.json).

Private TA code inspection shows a zero-template branch that returns `-208`;
another invalid-template branch uses the same error. The correction therefore
does not translate that error generically. It queries the full TA template
list, returns a nonmatch only when that query succeeds with zero templates,
and retains enumeration errors. It also returns a recognized device print
outside the caller gallery, as required for fprintd duplicate detection, while
leaving the authentication match null. The ARM64 driver/core tests passed;
the fresh `fprintd-emptydb` fixture retains the same volume-button interaction.

The first corrected-driver fixture stopped before enrollment because the
private generator's umask gave the new `/usr/lib64` overlay directory mode
0700. The exporter correctly preserved that mode, making the system library
path inaccessible to unprivileged services; the system bus repeatedly failed
and fprintd reported connection refused. The old buttons image has mode 0755;
`dump.erofs` confirmed mode 0700 in this failed image. No broker call, RPMB
callback or enrollment occurred. All fingerprint services stopped cleanly,
then UART reset and the exact fastboot serial were verified before stopping
the host. See [the result](fprintd-emptydb-result.json).

The corrected generator explicitly sets that public system directory to 0755
while the enclosing host vault remains private. The fresh `fprintd-libdir` run
uses the same tested driver and physical readiness controls. Its exported
library-directory permissions are checked before launch.

Host preparation initially ran out of workspace disk space before any boot
attempt. Five obsolete generated rootfs images from completed preflight and
missed-touch runs were removed after checking their recorded SHA256 hashes;
all source overlays, manifests, UART/results, credentials and receipts were
retained. The private pruning inventory records each removed generated image.
The failed preparation remains under an `-unbooted-disk-full` directory.
Preparation then succeeded, and the corrected image's `/usr/lib64` is verified
as 0755 in EROFS itself.

The corrected `fprintd-libdir` fixture now passes the automatic enforcing
handoff with no failed units. fprintd starts successfully and the client is
waiting for a fresh Volume Up press before enrollment; no readiness event had
occurred at the [saved checkpoint](fprintd-libdir-waiting.json). Its USB host
remains running. This establishes working service startup and device-side
readiness; it does not yet establish successful enrollment or matching.


A subsequent physical Volume Up press on `fprintd-libdir` advanced the empty
TA database through duplicate checking (`enroll-stage-passed`) and entered real
enrollment. fprintd then reported authorization-socket `Permission denied`.
The AVC identifies `fprintd_t -> unconfined_service_t:unix_stream_socket
connectto`, contradicting the earlier PID1 peer-label prediction. The broker
was never activated, there were no RPMB callbacks or biometric exports, and
all fingerprint services stopped cleanly. UART reset and the exact fastboot
serial were verified before host termination. See
[the final result](fprintd-libdir-result.json). The earlier waiting checkpoint
is historical; that run has ended.


The `fprintd-peer` candidate adds a dedicated confined SELinux broker domain
and an exact executable label. Its supplementary policy gives fprintd peer
connection access to that domain while retaining the existing socket inode
permissions. Offline checks prove preservation outside the two new types,
no generic unconfined-service connection grant, no fprintd credential reads,
and no broker access to private/generic TEE, RPMB or sensor devices. The normal
base-policy checks and all five broadening mutations still pass. The exported
broker label was verified from selective EROFS extraction's xattr value; the
host's policy was not loaded or changed. The controller will record actual
process domains and object labels before orderly shutdown.


The dedicated-peer fixture has booted with an automatically accepted enforcing
handoff and no failed units. It is waiting at the physical Volume Up enrollment
gate; its USB host remains live. See [the checkpoint](fprintd-peer-waiting.json).
The broker's real request handling, enrollment, matching and rejection remain
pending physical interaction. Local libfprint 1.5 and the inactive two-module
SELinux package have also built successfully; no package was published or
installed on daily sam-sargo in this iteration.

The subsequent Volume Up press reached the dedicated broker socket but systemd
failed to execute its newly labeled binary (`203/EXEC`, PID1 `execute` denial).
No broker request ran, no RPMB callbacks occurred, and no biometric records
were exported. All fingerprint services stopped; UART reset and fastboot serial
99NAY1AZG1 were verified before stopping the host. The waiting checkpoint above
is historical. See [the result](fprintd-peer-result.json).

The `fprintd-exec` candidate corrects the exact executable permission and checks
broker startup before presenting the enrollment readiness screen. The lab
service uses `Type=exec`, no restart, and a single start allowance. A root and
dedicated-domain peer check precedes an invalid-version request; the response
must be `-EPROTO` with a zero token. The native broker rejects that version
before opening credential state or a TEE session. Protocol tests reject wrong
peers, truncated responses, wrong status, nonzero token data and timeout, while
accepting fragmented reads. Real enrollment and each verification phase still
wait independently for a fresh Volume Up press/release; Volume Down cancels.

The corrected `fprintd-exec` run passed the enforcing systemd handoff with no
failed units, then passed the real broker protocol check in
`pocketfed_fpc_auth_t`. It is waiting at the enrollment Volume Up gate, with
the USB host retained. See [the checkpoint](fprintd-exec-waiting.json).
This accepts broker execution and rejected-request handling; genuine token
authorization, enrollment and matching through this confined service remain
pending. The requested desktop behavior is PIN once after reboot, followed by
fingerprints, as recorded in [the acceptance criteria](../acceptance.md).

The `fprintd-exec` run subsequently completed enrollment and a same-finger
match under enforcing SELinux, with fprintd and the authorization broker in
their separate confined domains. Sam used the **left index finger**, although
the harness assigned the metadata label `right-index-finger`. Both new records
were collected privately with complete hashes before reboot. The different-
finger phase returned `verify-unknown-error`: firmware command `-211`.
All services stopped cleanly, and UART reset plus the exact fastboot serial
were verified before host termination. See [the result](fprintd-exec-result.json).

Stock HAL/TA analysis identified the missing identification completion command.
The 1.6 driver candidate now performs it for successful matches and nonmatches,
requires its success, and does not persist any adaptive template changes.
Stateful API tests reject a second scan when completion is omitted, cover
completion failures and cancellation, and retain gallery binding. All seven
ARM64 unit/FPC suites pass. A verification-only client and `fprintd-reopen`
generator restore the saved records without an initialization marker or an
enrollment request. The two verification phases retain physical readiness
gates. Hardware confirmation of this correction and restored persistence is
the next check.

The `fprintd-reopen` hardware check passed: the saved finger matched and a
different finger returned `verify-no-match` on the next scan. No EnrollStart
was issued. Both restored records and the Gatekeeper service credential had
unchanged hashes afterward, and all services stopped cleanly. The kernel
rebooted to verified fastboot before USB hosting ended. See
[the reboot result](fprintd-reopen-result.json). This validates the corrected
driver's native fprintd path on test-sargo; daily-phone Settings enrollment and
Phosh unlock remain the revised desktop acceptance target.
