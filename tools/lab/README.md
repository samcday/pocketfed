# Lab relay

`relay.py` drives the USB relay module on the lab host so agent sessions can
hard power-cycle a wedged board without a human. It needs only Python 3.11+.

## Hardware

The module is Phipps Electronics' "4 Channel 5V Low Level USB Relay Module":
a dcttech `USBRelay4` (V-USB HID, `16c0:05df`, manufacturer
`www.dcttech.com`, no USB serial string, low speed). It is switched with
8-byte HID feature reports (`FF`/`FD` plus the channel) and reports its coils
as a bitmask in byte 7 of the same report, next to a 5-character board ID.
The listing rates the contacts at 10 A 30 V DC; this module switches
low-voltage DC only, never mains.

"on" means the coil is energised: NO closes and NC opens. Every coil is off
when the module is unplugged or the host is down.

| Channel | Name | Wiring |
|---|---|---|
| 1 | `db410c-power` | DB410c 12 V positive lead through COM and NC |
| 2–4 | unassigned | |

`relay.toml` holds this map and the DB410c's identities.

## DB410c wiring

The DB410c takes 6.5–18 V on a 4.75/1.7 mm (EIAJ-3) centre-positive barrel.
Unplug the supply from the wall, then route only its positive lead through
channel 1: supply + to COM1, NC1 to the board's +, negative uninterrupted.
Splice the supply's lead or use barrel pigtails; insulate every joint and keep
the module on a non-conductive surface. Before connecting the board, confirm
with a meter that COM1–NC1 conducts while the coil is off and opens after
`relay.py on 1`, then run `relay.py off 1`.

Because the load hangs off NC, the board stays powered whenever the relay is
idle, unplugged or its host is off; a power cycle energises the coil briefly.

## Setup

The module's hidraw node is root-only until a udev rule names it and grants
the desktop session access, as `70-usb-serial-uaccess.rules` does for the
lab UARTs. The rule matches the physical USB port, since the module has no
serial number; regenerate it if the module moves.

```sh
tools/lab/relay.py udev-rule | sudo tee /etc/udev/rules.d/70-lab-relay.rules
sudo udevadm control --reload
sudo udevadm trigger --settle --subsystem-match=hidraw
tools/lab/relay.py status
```

Keep the `70-` prefix: `uaccess` only takes effect before
`73-seat-late.rules`.

## Use

```sh
tools/lab/relay.py status
tools/lab/relay.py pulse 3
tools/lab/relay.py db410c-power-cycle [--json] [--uart-log FILE]
```

`db410c-power-cycle` refuses (exit 2) while the board looks in use: another
process holds or locks its UART, `smoo-host --product-id 0xBEE1` is running,
a `fastboot`, `fastboop` or `pocketfed-liveboot` process names its serial (or
a `fastboot` runs without `-s`), or the board is on USB as the `dead:bee1`
smoo gadget. The calling shell and its ancestors are ignored. Use `--force`
only for a board your own session is using, such as your own `smoo-host`
serving a wedged liveboot. `on` and `pulse` run the same check before they
cut the board's power.

Otherwise it locks the relay and the UART, cuts power for `off_seconds`,
restores it with SIGINT, SIGTERM and SIGHUP held back, and watches USB and
the console until fastboot appears.

| Exit | Meaning |
|---|---|
| 0 | back in U-Boot fastboot |
| 1 | usage, configuration or relay I/O error, or interrupted (power restored) |
| 2 | refused: the board or the relay is in use |
| 3 | relay module missing or inaccessible |
| 4 | power returned and the console showed a boot, but no fastboot |
| 5 | no console output and no fastboot |
| 6 | the board never left USB while its power was cut: check the wiring |

A `SIGKILL` during the cut leaves the board unpowered; `relay.py off 1`
restores it.
