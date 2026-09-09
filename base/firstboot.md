# Initial configuration before the greeter

Factory images leave locale, timezone, keymap, and hostname unset. Their
`/etc/machine-id` contains `uninitialized`, so systemd performs its normal first
boot initialization and service presets. With the upstream service command,
`systemd-firstboot` asks for configuration on the console before `sysinit.target`;
on the supported phones that console may only be reachable over UART.

The vendor drop-in
`mkosi.extra/usr/lib/systemd/system/systemd-firstboot.service.d/50-pocketfed-noninteractive.conf`
runs `systemd-firstboot` without interactive prompt options and sends its output
to the journal. Missing settings remain unset for graphical setup. The service
keeps its upstream credential imports, ordering, and first-boot completion
semantics. Root account provisioning is unchanged.

This also preserves fastboop personalization: its stage0 writes
`firstboot.locale`, `firstboot.locale-messages`, `firstboot.keymap`, and
`firstboot.timezone` into `/run/credstore`. `systemd-firstboot` reads and applies
these credentials without requiring `--prompt-*`. Existing settings retain
precedence over incoming credentials. Do not mask the service or add image-wide
locale/timezone defaults, since those approaches would prevent this import.

Run `base/test-firstboot` on a systemd host. It invokes the command from the
drop-in against disposable roots with no standard input, checking factory,
fully personalized, partially personalized, and already configured cases.
To test the installed image policy, run the script inside the image and pass
`/usr/lib/systemd/system/systemd-firstboot.service.d/50-pocketfed-noninteractive.conf`.
The test only writes beneath its temporary directory.

Device acceptance still requires a fresh factory boot without credentials or
console input, a working Phrog setup flow, and a subsequent reboot/login. A
separate fastboop boot should confirm its host-derived locale/timezone reach
the greeter. The filesystem regression does not prove graphical setup or
systemd credential delivery at runtime.
