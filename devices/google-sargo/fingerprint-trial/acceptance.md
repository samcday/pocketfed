# Requested fingerprint behavior

Sam clarified the cold-boot requirement on 12 September 2026:
**PIN once after reboot, then fingerprints.** A fingerprint-only mechanism for
unlocking an inactive encrypted home before the first PIN is not requested.
Preserve the encrypted homed home and the ordinary PIN recovery path.

Sam subsequently removed **Phrog login** from the goal. Completion requires
real results on **sam-sargo**: GNOME Control Center can enroll fingerprints;
enrolled fingers unlock the normal Phosh lockscreen after initial PIN login;
different fingers are rejected; PIN fallback and scan cancellation work; and
enrollment persists across reboot with the same initial-PIN behavior. Preserve
PIN recovery if the home is cold or its keys have explicitly been locked. Do
not bypass account checks or store Sam's PIN to avoid a prompt. Phrog-specific
PAM changes and home-reference retention work are outside this revised goal.

Dedicated test-sargo is the development and recovery environment, not final
acceptance for the daily phone. Its volume-button harness waits on device for
readiness. Laboratory credential authorization, enrollment, and a same-finger
match have passed. After reboot with the privately retained enrollment, the
corrected 1.6 driver matched that finger and rejected a different one under
enforcing SELinux; the records and credential remained unchanged. A subsequent
trial using the packaged listener, loaders, broker and libfprint also matched the
saved finger and rejected a different one, with clean shutdown and no change
to the records. Documented lab firmware and operational drop-ins remain part
of that result. The daily-phone Settings/Phosh path still needs acceptance.
