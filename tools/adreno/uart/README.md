# UART console file transfer

Four small helpers for driving a board whose **only** channel is a serial console:
no network, no adb, no shared filesystem. Written for the DragonBoard 410c during
[pocketfed#80](https://github.com/samcday/pocketfed/issues/80), where a ~1 MB
`eglretrace` binary had to reach a RAM-rooted guest without rebooting it.

They assume a root shell already sitting at a prompt on the serial line, 115200 8N1.
They do not log in, reset, or otherwise recover a board.

## The pieces

| Script | Role |
|---|---|
| `uart-console.py` | Long-running daemon. Holds the tty exclusively (`flock` + `TIOCEXCL`), appends everything read to a log, and accepts JSON request lines on a FIFO. |
| `uart-run.py` | Runs one shell command and waits for its completion marker. |
| `uart-push.py` | Host → guest file copy, chunked base64 with per-chunk SHA256 readback and retry. |
| `uart-pull.py` | Guest → host file copy, `xz` + base64 with a SHA256 check. |

Only the daemon opens the device, so concurrent helper invocations cannot interleave
bytes on the wire or race for the port. Everything the board prints — including
kernel messages that arrive between commands — lands in the one log file.

```sh
./uart-console.py --device /dev/serial/by-id/usb-FTDI_... \
                  --log /tmp/board.log --fifo /tmp/board.fifo &

./uart-run.py --fifo /tmp/board.fifo --log /tmp/board.log 'uname -r'
```

## Pacing, and why it matters

The board's console has no flow control, so the host must not outrun the guest's
tty input buffer. Two profiles are used:

- **Commands** go out byte-by-byte with a 2 ms delay. Short, and robust.
- **Bulk data** goes out in 256-byte blocks with a 35 ms delay between blocks,
  about 7.3 kB/s on the wire, roughly 63% of line rate. Measured end-to-end
  throughput including per-chunk verification was **~5.3 kB/s** of source bytes;
  1,070,228 bytes transferred in ~205 s with no chunk retries.

Per-byte pacing is far too slow for anything megabyte-sized — that is what the
`block`/`delay` mode in the daemon exists for.

## How `uart-push.py` avoids losing bytes

Bulk transfer needs the console in raw mode, but the interactive shell resets the
terminal around every command it runs. So raw mode is entered *inside* the receiving
command and left when it finishes:

```sh
printf 'RDYTOK\n'; stty -icanon -echo min 1 time 0; head -c <N> > <part>; stty icanon echo; sha256sum <part>
```

`-echo` matters for more than tidiness: without it the guest echoes every byte back,
halving effective throughput and flooding the log. `head -c <N>` takes an exact byte
count, so the receiver stops on its own and the shell prompt returns predictably.

The `RDYTOK` handshake exists because the shell may read ahead past the newline that
ends the command line. The sender waits for that token, pauses briefly, and only then
starts the payload, so no data can be swallowed by the shell's own line reader.

Each chunk's base64 text is hashed on both ends; a mismatch re-sends that chunk only,
not the whole file. The assembled file is hashed once more after `base64 -d`.

Markers are emitted split (`"__MK" "1234abcd__rc=$?"`) so the shell's echo of the
command never matches the pattern the host is waiting for.

```sh
./uart-push.py --fifo /tmp/board.fifo --log /tmp/board.log \
               --src ./payload.tar.xz --dst /run/payload.tar.xz
./uart-pull.py --fifo /tmp/board.fifo --log /tmp/board.log \
               --src /run/crash.dump --dst ./crash.dump
```

`uart-pull.py` compresses on the guest before encoding, so it suits dumps and logs.
It decompresses on arrival and reports both hashes. Keep the console log in a temp
directory: bulk transfers make it large.

## Limits

No login handling, no U-Boot interaction, no board recovery. A guest that stops
draining its console stalls a transfer until the timeout. The SHA256 readback is
the only integrity guarantee — the serial link itself has none.
