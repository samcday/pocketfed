# Inactive homed homes and fingerprint login

Sam selected **PIN once after reboot, then fingerprints** on 12 September 2026.
The cold-start key-release architectures below are background research, not
required implementation for the current goal. Preserve normal PIN activation
and encrypted-home account checks; see the
[accepted behavior](../../devices/google-sargo/fingerprint-trial/acceptance.md).

Source review only, 2026-09-11. Checked local systemd commit
`8b8d819944b6713bcb8b05d8e643c21de3770d08`, following its
[AGENTS.md](/var/home/sam/src/systemd/AGENTS.md). No PAM/home changes, credential
store access, live authentication tests or device operations were performed.

## What works today

**A fingerprint match can authenticate an existing session, but the checked
homed implementation cannot turn that match or an Android HAT into the key for
an inactive encrypted home.** The current desktop work therefore needs separate
results for an active home, an inactive home, and a locked encrypted home.

`pam_systemd_home` account/session hooks first try `RefHome()`, which can take a
reference to an already active home without another unlock credential. If the
home is inactive or locked, they switch to `AcquireHome()` and collect a supported
credential. Authentication hooks always request authentication. An earlier
module's `PAM_AUTHTOK`, if present, becomes a candidate password. See
[acquire_home()](/var/home/sam/src/systemd/src/home/pam_systemd_home.c:532),
[authentication hook](/var/home/sam/src/systemd/src/home/pam_systemd_home.c:780),
[session hook](/var/home/sam/src/systemd/src/home/pam_systemd_home.c:847), and
[account hook](/var/home/sam/src/systemd/src/home/pam_systemd_home.c:977).

The prepared Phosh fingerprint helper rejects password conversations and requires
`pam_acct_mgmt()` success. Its homed account rule consequently refuses an
inactive/locked home that needs a password. The candidate greetd stack retains
the homed account check; a fingerprint match can still be followed by the normal
PIN prompt for cold activation. Neither outcome should be reported as
fingerprint-only cold login. See
[worker](/var/home/sam/src/pocketfed/packages/fingerprint-desktop/phosh-fingerprint-worker.c:15),
[Phosh PAM service](/var/home/sam/src/pocketfed/packages/fingerprint-desktop/phosh-fingerprint.pam:3),
and [greetd candidate](/var/home/sam/src/pocketfed/packages/fingerprint-desktop/greetd.pam.candidate:15).

## Existing interfaces and missing pieces

| Mechanism | Current support and limits |
| --- | --- |
| Password or recovery credential | Supported. A transient `secret.password` array can supply an already enrolled credential. It must both authenticate the signed user record and unlock its storage. A random additional credential need not be Sam's PIN. |
| PKCS#11 | Supported. Homed generates an independent secret, stores its public-key-encrypted form and a verification hash, then obtains the decrypted secret through the token's `C_Decrypt()` operation. A suitable provider must already exist. |
| FIDO2 | Supported for authenticators implementing `hmac-secret`. A stable secret is derived from a credential and salt, with optional user verification. Biometric verification is possible only if the authenticator itself supplies that capability; the Sargo FPC sensor/TA is not thereby a FIDO2 device. |
| Fingerprint match / Android HAT | No input field or consumer exists in the checked homed code. A fresh success indication supplies no existing home-unlock secret. |
| External raw LUKS volume key | No public home1 method/secret field accepts one. Homed's internal cached volume key is not a supported external key-injection interface. |

The actual secret parser accepts passwords, token PINs, and permissions for
PKCS#11 protected authentication and FIDO2 presence/verification; it has no
biometric token or raw-key field. See
[secret schema](/var/home/sam/src/systemd/src/shared/user-record.c:623),
[home1 methods](/var/home/sam/src/systemd/man/org.freedesktop.home1.xml:251),
[token credential formats](/var/home/sam/src/systemd/docs/USER_RECORD.md:702), and
[homectl enrollment options](/var/home/sam/src/systemd/man/homectl.xml:575).

The internal LUKS cache lives in homed's private session keyring. Deactivation
and locking flush it; the activation and unlock workers start with an empty
password cache. Retaining or injecting that key would not establish the missing
biometric authorization. See
[key upload](/var/home/sam/src/systemd/src/home/homework-luks.c:275),
[cache reader](/var/home/sam/src/systemd/src/home/homework-password-cache.c:19),
[activation](/var/home/sam/src/systemd/src/home/homework.c:907),
[deactivation cleanup](/var/home/sam/src/systemd/src/home/homework.c:1054), and
[lock/unlock](/var/home/sam/src/systemd/src/home/homework.c:1910).

This remains upstream work: the current upstream TODO explicitly retains
fingerprint authentication under homed. The local copy agrees at
[TODO.md:1133](/var/home/sam/src/systemd/TODO.md:1133).
[Upstream TODO](https://github.com/systemd/systemd/blob/main/TODO.md).

## The credible path beyond a boolean match

Android uses a signed authentication token as evidence that permits a
Keymaster/KeyMint operation; the token itself is not the persistent encryption
key. The authenticator emits the token, and the crypto TA checks it before
allowing use of an authentication-bound key. Tokens include freshness data and
use a per-boot shared HMAC key. A stable home credential therefore cannot simply
be computed by hashing a new HAT each time.
[AOSP authentication design](https://source.android.com/docs/security/features/authentication).

The bounded next technical question is whether this Sargo Keymaster/FPC pair can
release or use a separately provisioned, authentication-bound key only after a
fresh fingerprint proof, with the expected SID, challenge, authentication type
and enrollment/revocation behavior. That has not been implemented or validated.
It requires more than making the legacy QSEECOM transport work.

If that primitive can be established, a new Linux credential provider could
recover an independently enrolled homed unlock secret and hand it to the
existing password interface transiently, or implement a compatible PKCS#11
provider. Such a bridge could avoid a homed core change, but it is still new
security-sensitive integration work. A native HAT input/provider inside homed
would instead require explicit upstream API and implementation work. This note
does not select or design the cryptographic construction.

The enrollment broker's current 64-byte service credential is deliberately stored
in a root-only host file so it can obtain Gatekeeper enrollment HATs. It is not
released by fingerprint hardware. Reusing it directly as a home credential would
not provide the required biometric-bound protection. Its password-type enrollment
HAT also must not be treated as proof of a fingerprint match.

Homed already models multiple passwords, but enrollment must update its signed
record and storage together. Its synchronization code requires the plaintext for
each retained password hash and rebuilds the effective LUKS slots. Preserving
Sam's PIN therefore needs a normal, transient authenticated setup interaction;
it does not require storing that PIN. Adding an unmanaged `cryptsetup` slot is
not a supported shortcut because subsequent homed password updates can remove
it. See
[effective passwords](/var/home/sam/src/systemd/src/home/homework.c:1134),
[password update](/var/home/sam/src/systemd/src/home/homework.c:1761), and
[LUKS slot synchronization](/var/home/sam/src/systemd/src/home/homework-luks.c:3700).

## Proposed controlled live tests

First compare the installed systemd package/version with the source reviewed
here. Observe state through `GetHomeByName`, which returns only basic user and
home-state metadata, rather than retrieving the privileged user record:

```sh
busctl call org.freedesktop.home1 /org/freedesktop/home1 \
  org.freedesktop.home1.Manager GetHomeByName s sam
loginctl show-user sam -p State -p Linger -p Sessions
```

These are proposed metadata checks, not commands run by this review. Mount
presence can be checked from mount-table metadata without opening files beneath
the home. A logged-out-looking greeter is not sufficient evidence that the home
is inactive; other sessions or references may keep it open.

| Observed precondition | Controlled test and interpretation |
| --- | --- |
| Home `active`, established PIN login | Lock the ordinary Phosh screen, verify fingerprint success, rejection and cancellation, then recheck home state. Success proves active-session authentication only. |
| Home `inactive`, before any Sam login after a coordinated reboot or after all sessions naturally close | Attempt fingerprint login through Phrog and record both match result and final PAM/account/session result. With the current candidate, needing the ordinary PIN is expected. A desktop appearing with an unusable home is a failure. |
| Home explicitly `locked`, as a separate coordinated test with recovery available | Confirm that a boolean fingerprint match alone does not bypass homed's unlock requirement. Full key-dropping suspend is a distinct requirement from an ordinary screen lock. |

Do not force-deactivate or lock the live home merely to gather this evidence.
Homed's lock path freezes the user's session; a functioning recovery UI must run
outside that user context. Its PAM documentation explicitly calls out that
constraint. See
[suspend semantics](/var/home/sam/src/systemd/man/pam_systemd_home.xml:49).
