# DB410c (apq8016-sbc) liveboot userspace overlay

Complete trial overlay for the DragonBoard 410c profile
(`profiles/apq8016-sbc.json`), copied from `../overlay` (the default
liveboot overlay) so `prepare-fixture.py --overlay` still receives one whole
overlay. Keep this copy synchronized with the default overlay when that one
changes.

On top of the default overlay's masks, this disables units that the cached
PocketFed device image enables by preset but that target hardware or services
outside this trial. Each was checked against the source image: most are bound
to Sargo/Pixel devices that do not exist here (81voltd also carries a
restart-on-failure drop-in, so it would restart-loop), while `clatd` is not
SoC-specific and is masked only because carrier tethering is out of scope for
this USB-root checkpoint:

- `81voltd.service`: Sargo battery/charger management with a restart-on-failure drop-in.
- `clatd.service`: carrier 464XLAT tethering daemon.
- `pocketfed-sargo-mcfg.service`, `pocketfed-sargo-network-search.service`,
  `pocketfed-sargo-uim-select.service`: Sargo modem carrier configuration.
- `pocketfed-swclock-offset.service`, `pocketfed-swclock-offset-save.service`,
  `pocketfed-swclock-offset-save.timer`: PM660 RTC wall-clock offset restore.
- `blob-wrangler.service`: Pixel vendor firmware extraction.
- `q6voiced.service`: Sargo Q6 voice call-audio routing (no q6voice card here).

Left enabled on purpose: `rmtfs` (self-skips without `/dev/qcom_rmtfs_mem1`),
`tqftpserv` (generic QRTR service), and `systemd-boot-check-no-failures`
(parity with the Sargo liveboot behavior). WCN3620 WLAN/BT firmware and
display/input bring-up are later subsystem work, not part of the handoff
checkpoint.
