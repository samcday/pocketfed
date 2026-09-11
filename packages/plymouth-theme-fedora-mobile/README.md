# Fedora Mobile Plymouth theme

A restrained black boot screen with an original Fedora-blue orbit and readable
Fedora / MOBILE typography. The orbit is 104 logical pixels across; Plymouth's
device scale makes it 208 pixels on a 2x display. A 240-pixel-wide composition
fits portrait phones while proportional placement also works in landscape.
The theme has no GPU, firmware, custom Plymouth plugin or script-plugin dependency.

This is a PocketFed theme, not a claim of official Fedora design endorsement.
All new code and geometric artwork here are MIT licensed. `generate-assets.py`
renders original geometry and Cantarell text; no Fedora logo or upstream spinner
artwork is copied. Cantarell is supplied by Fedora under its own font license;
font files are not bundled. The stock spinner package's `keymap-render.png` is
referenced by a relative symlink, so the pre-rendered keyboard-layout atlas stays
matched to the installed Plymouth renderer. That file is not copied into this RPM.

## Behavior

- Stock `two-step` handles password entry, ordinary questions, keyboard layout
  and Caps Lock indicators, messages, updates, shutdown, and display hotplug.
- Password bullets are dark on a light field, as is the plugin's built-in
  black ordinary-question text. The 260-pixel lock plus entry fits even a
  320-logical-pixel display. No touch keyboard is added; early encrypted-root
  prompts still need an input method supplied by the OS or an external keyboard.
- Messages remain visible. Update modes use a real progress bar and Plymouth's
  existing translated titles rather than a made-up boot percentage.
- There is no theme-created end delay, minimum splash duration, or late animation.
- The renderer decides DPI scaling and simpledrm/native-DRM handoff. This theme
  does not turn an invalid firmware framebuffer into a working display, start
  Plymouth earlier, change `DeviceTimeout`, load Adreno, or fix MSM modesetting.
  On a simpledrm display without physical-size metadata, validate the selected
  device scale separately; a phone-specific `DeviceScale=2` may be appropriate.

## Package locally

```sh
python3 packages/plymouth-theme-fedora-mobile/prepare-srpm.py /tmp/fedora-mobile-srpm
rpmbuild -bb --define '_topdir /tmp/fedora-mobile-srpm' --define '_tmppath /tmp' \
  --define 'dist .fc46' \
  /tmp/fedora-mobile-srpm/SPECS/plymouth-theme-fedora-mobile.spec
```

The SRPM is self-contained. Its build requirements are Python Pillow, fontconfig
and Cantarell. `%check` verifies the animation, prompt contrast, geometry and
mode settings. `build.json` records the actual validation and artifacts.

The next packaging step, once the candidate is accepted, is:

```sh
copr-cli build --chroot fedora-rawhide-aarch64 --chroot fedora-rawhide-x86_64 \
  samcday/pocketfed \
  /tmp/fedora-mobile-srpm/SRPMS/plymouth-theme-fedora-mobile-0.1.0-1.fc46.src.rpm
```

This directory does not submit a build, install a package, select a theme, or
rebuild the initramfs. Image integration should install the signed COPR package,
allowlist its package name, and select `Theme=fedora-mobile` before composing
the initramfs. Verify that dracut retains the keymap symlink target, the label
plugin/font and the chosen simpledrm renderer. The current user-requested trial
uses normal COPR/image builds and installed boots on sam-sargo because the test
phone is unavailable. Future local trials follow `tools/liveboot/README.md`.
Preserve the verbose UART liveboot default; a splash-specific trial can
explicitly opt into graphics.

## Render without affecting the host boot or display

Install the local test tools: Plymouth with its X11 renderer and spinner theme,
Xvfb, bubblewrap, Python Pillow, libX11 and libXtst. Run:

```sh
/usr/bin/python3 packages/plymouth-theme-fedora-mobile/preview.py \
  /tmp/fedora-mobile-preview --geometry 1080x2220 --scale 2
```

This starts actual `plymouthd` and its stock two-step plugin under Xvfb in an
isolated user/mount/network namespace with a private `/run` and `/dev`. It has
no host GPU device or network access, and changes no host theme configuration.
GLX is disabled; only software pixel rendering is exercised. Screenshots cover
boot animation, message, password bullets, visible question entry, four update
modes, deactivate/reactivate, shutdown and reboot. Synthetic prompt responses
are checked end to end. This is not evidence of a tested DRM handoff on a phone.

Repeat at `--geometry 720x1280 --scale 2` and
`--geometry 1280x720 --scale 1` to inspect compact portrait and landscape layouts.
Generated screenshots and RPM staging belong outside this source directory.

## Upstream references

The configuration and asset interface were checked against the local upstream
Plymouth checkout at `016708af9748219265229e1ee28dc7fdeafb649f`:

- [two-step plugin](https://gitlab.freedesktop.org/plymouth/plymouth/-/blob/016708af9748219265229e1ee28dc7fdeafb649f/src/plugins/splash/two-step/plugin.c)
- [entry rendering](https://gitlab.freedesktop.org/plymouth/plymouth/-/blob/016708af9748219265229e1ee28dc7fdeafb649f/src/libply-splash-graphics/ply-entry.c)
- [keyboard atlas interface](https://gitlab.freedesktop.org/plymouth/plymouth/-/blob/016708af9748219265229e1ee28dc7fdeafb649f/src/libply-splash-graphics/ply-keymap-icon.c)
