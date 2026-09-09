# Native runtime validation

Validated on 2026-09-10 against upstream `v0.1.1`
(`0d39c507d7464dc77bdfe256b22460d91e7c0414`) plus the three production
patches in this package. Exact native library versions are recorded in
`native-environment.txt`.

`timezone-regression.patch` contains the test source. It applies on top of the
production timezone patch and adds only `#[cfg(test)]` code. It is deliberately
separate from the SRPM submitted to COPR as build 10967394; production code is
identical in the tested and submitted trees.

Run `./run-native PREPARED_SOURCE_DIRECTORY [RESULTS_DIRECTORY]` in a disposable
build environment with the package's build dependencies, `patch`, `xvfb-run`,
`dbus-run-session`, and `timeout`. The source must already have the production
patches and a working Cargo vendor configuration. If ImageMagick's `import`
command is available, the test also records 360×740 screenshots at scale 1.

The runner adds the supplemental test if necessary, checks and builds the app,
then exercises its actual GTK timezone page against a mock timedate1 service
on a private D-Bus bus. It checks:

- A failed timezone-list request blocks Next and reveals Retry.
- Retry loads the offline list and selects the current timezone, UTC.
- A rejected timezone write keeps Next blocked and the saved timezone unchanged.
- Retry saves Australia/Sydney, clears the error, and enables Next.

The separate full-app startup check uses another private bus with no locale,
timezone, or home services. With `G_DEBUG=fatal-criticals`, it initializes all
page templates and remains alive for five seconds. Timeout status 124 is the
expected successful result. Missing-service warnings are intentional.

Results: native compile check and linked build passed; the timezone regression
test passed; the full-app startup check passed. Compressed logs are retained
beside this document. The initial compile check reported an unused import;
the production patch removed that import before the linked build.

Screenshots show timezone selection, search, load failure, write failure, and a
render-only user-error fixture. The user fixture creates no account and does
not validate homed, AccountsService, or authentication. The Xvfb surface is
360×740 at scale 1; GTK reports a 350×730 content area inside its window shadow.
The phone's fullscreen presentation needs device confirmation. Hardware
validation remains necessary for the OSK, account creation, login, and imports.
