# Native runtime validation

Validated on 2026-09-10 against upstream `v0.1.1`
(`0d39c507d7464dc77bdfe256b22460d91e7c0414`) plus the production
patches in this package. Exact native library versions are recorded in
`native-environment.txt`.

`timezone-regression.patch` contains the test source. It applies on top of the
production timezone patch and adds only `#[cfg(test)]` code.
`handoff-and-locale-regression.patch` adds account and locale fixtures, plus
test-only hooks for temporary defaults and export paths.
`window-close-regression.patch` checks the running application's close and
completion actions. These supplemental
patches are deliberately separate from the SRPM. The initial validation
covered build 10967394; the expanded locale test exposed the nullable language
name bug fixed in the subsequent production fallback patch. Patch hashes in
`validated-patches.sha256` identify the final validated implementation.

Run `./run-native PREPARED_SOURCE_DIRECTORY [RESULTS_DIRECTORY]` in a disposable
build environment with the package's build dependencies, `patch`, `xvfb-run`,
`dbus-run-session`, and `timeout`. The source must already have the production
patches and a working Cargo vendor configuration. When starting with an earlier
source, the runner applies production patches 0004 through 0008 as needed before
the supplemental tests.
If ImageMagick's `import`
command is available, the test also records 360×740 screenshots at scale 1.

The runner adds the supplemental test if necessary, checks and builds the app,
then exercises its actual GTK pages against mock services on private D-Bus
buses, with temporary HOME and XDG directories. It checks:

- Configured Meson defaults, locale, and output paths survive Cargo builds.
  Generated source and the actual binary contain `/usr/share` and persistent
  `/var/lib/phosh-first-boot` paths; upstream `/usr/local/share` and `/run` paths
  are absent. The real binary's `--help` reports the installed defaults file
  without a fixture override. The same regression runs against the installed
  RPM binary during `%check`.
- A failed timezone-list request blocks Next and reveals Retry.
- Retry loads the offline list and selects the current timezone, UTC.
- Entering `New York` and mixed-case `sYdNeY` filters the popup to the matching
  city. Activating that filtered row selects the original timezone ID.
- A rejected timezone write keeps Next blocked and the saved timezone unchanged.
- Retry saves Australia/Sydney, clears the error, and enables Next.
- The real Create User button loads the wheel group from the defaults file.
- Back navigation is disabled while CreateHome is pending. A rejected CreateHome
  restores Back so the user can edit their settings and retry.
- Both dconf files, including the selected keyboard layout, are exported before
  the mock home service receives CreateHome.
- A CacheUser failure blocks Next; retry registers the account without calling
  CreateHome a second time.
- Once CreateHome succeeds, Back stays disabled through a CacheUser failure,
  its retry, and the final page. The user cannot change keyboard settings after
  the account's persistent handoff has been committed.
- A denied locale write leaves the previous locale unchanged and blocks Next;
  retry saves LANG and all five configured LC categories.
- An unknown locale name falls back to its raw locale string; C.UTF-8 also
  produces a usable label.
- Before account creation, the running application hides window title controls
  and stays visible after a window-manager close request. The explicit
  completion action still shuts down the application.

The separate full-app startup check uses another private bus with no locale,
timezone, or home services. With `G_DEBUG=fatal-criticals`, it initializes all
page templates and remains alive for five seconds. Timeout status 124 is the
expected successful result. Missing-service warnings are intentional.

Results: native compile check and linked build passed; configured package paths,
timezone, account handoff, locale, and window-close regression tests passed;
the full-app startup check passed. As a negative control, the published ARM64
`1.2` binary contains the incorrect development paths, and its executed `--help`
reports `/usr/local/share/phosh-first-boot/defaults.conf`. This defect was hidden
by the earlier native fixture's temporary defaults and output overrides.
Compressed logs are retained beside this document.

Screenshots show timezone selection, search, load failure, write failure, and a
render-only user-error fixture. The user fixture creates no account and does
not validate real homed, AccountsService, or authentication. The Xvfb surface is
360×740 at scale 1; GTK reports a 350×730 content area inside its window shadow.
The phone's fullscreen presentation needs device confirmation. Hardware
validation remains necessary for the OSK, account creation, login, and imports.
