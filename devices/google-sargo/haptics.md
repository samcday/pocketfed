# Sargo haptics

Validation for [sam-sargo issue #7](https://github.com/samcday/sam-sargo/issues/7)
on 6–7 September 2026 found working driver/feedbackd integration and a
missing device-theme package affecting short touch feedback.

## Device defaults

The phone only had feedbackd's generic `default.json`. Its `key-pressed`
and `button-pressed` patterns use 7 ms at magnitude 0.2. The upstream
[`google,sargo` theme](https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes/-/blob/v0.8.9/data/google,sargo.json)
sets both press events to 15 ms at magnitude 0.5. On 7 September, Sam
physically confirmed that this pattern can be felt.

PocketFed now packages the unmodified upstream `feedbackd-device-themes`
0.8.9 release in [COPR build 10954637](https://copr.fedorainfracloud.org/coprs/build/10954637)
and installs it in the Phosh image. The Phosh and device repository
allowlists retain this package, and CI checks package presence and validates
the Sargo and Fajita themes. See the [package record](../../packages/feedbackd-device-themes/README.md)
for source pinning and build checks.

With the configured theme left at `default`, feedbackd discovers the
`google,sargo` device-tree compatible and loads the packaged device theme.
Call/message vibration patterns are inherited from the generic theme.
No custom theme, strength preference, driver, or voltage change is required.

## Tested phone

| Component | Tested value |
| --- | --- |
| Image | `ghcr.io/samcday/sam-sargo:rawhide` |
| Base image digest | `sha256:3a9430a43d718f2a5d7fd993941790e47ba987e2d292ebf078684d40bdf6cf04` |
| Kernel | `7.1.2-0.pocketfed.sdm670.6.fc46.aarch64` |
| feedbackd | `0.8.9-4.fc45.aarch64` |
| Phosh / Stevia | `0.57.0-1.fc46.aarch64` |
| Settings | Profile `full`, maximum haptic strength `1.0`, DND off |
| Touch trial | Exact upstream Sargo JSON, SHA-256 `7430e68b1eb01436ec9bbd66ae11ebec0df4f7550d3ba7ed351f5bb13532a4da` |
| Other local packages during touch trial | GTK `4.23.4-1.1.pocketfed.fc46` override; layered Tailscale |

The input device is named `drv2624:haptics`; discover it by name because
event and I2C bus numbers can change across boots. feedbackd had the
device open with working permissions and exposed its Haptic interface.

Sam confirmed the SMS/call patterns and clean stopping, including a
post-reboot message pattern, explicit call-feedback cancellation, and
test-client disconnection. A real post-reboot SMS vibrated, and a real
call's vibration stopped on local rejection. The weak 20% pulse was not
perceptible; a 300 ms pulse at 50% was felt and stopped.

Automated profile checks reached the driver in `full`/`quiet`, produced no
vibration in `silent`/DND, and restored the previous profile when DND was
disabled. These API/driver checks are separate from physical observations.
The full real-application acceptance matrix is not complete: in-session
answer, successful cellular caller hangup, and post-suspend real call/SMS
checks remain unverified. Desktop SIP hangup, a Phoc crash, and a
ModemManager suspend crash were separate failures observed during testing.

Real SMS validation also required starting Chatty's background service and
a trial WirePlumber role-routing correction. The results above must not be
read as proof that this base image alone passes every notification case.
The device-theme package fixes touch defaults; it does not fix application
startup or audio routing.

## Live deployment

The first live RPM installation was cancelled during dracut on 6 September.
The physical touch trial therefore used an exact copy of the upstream JSON
at `~/.config/feedbackd/themes/pocketfed-sargo-upstream.json`, selected with
the `org.sigxcpu.feedbackd theme` setting. The original setting was unset.
On 7 September the signed RPM was successfully live-applied and staged for
the next boot. At 08:54 AEST the temporary file was removed and the original
unset preference restored, giving the normal `default` setting. A theme
expansion check with the phone's `google,sargo` compatible selected the
packaged device theme and inherited `default`. Its SHA-256 matches the
physically confirmed trial. Profile `full` and maximum strength `1.0` were
preserved. No reboot was needed for live application; a reboot of this new
package deployment has not been tested. The base image digest is unchanged,
and publication of an image containing the package remains pending.

## Verify

Run user commands on the existing graphical session bus:

```sh
as_sam() {
    runuser -u sam -- env XDG_RUNTIME_DIR=/run/user/1000 \
        DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "$@"
}
rpm -q feedbackd feedbackd-device-themes
fbd-theme-validate /usr/share/feedbackd/themes/google,sargo.json
as_sam gsettings get org.sigxcpu.feedbackd theme
as_sam gsettings get org.sigxcpu.feedbackd profile
```

The normal theme setting is `default`. Check that no user theme shadows
the packaged one, then physically assess OSK and Phosh keypad presses.
Successful theme validation alone is not physical proof of vibration.
