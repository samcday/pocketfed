# tools/adreno

Host-side helpers for the DragonBoard 410c Adreno A306 investigation
(samcday/pocketfed#80). Two independent things live here:

- **`bake-payload.sh`** — put trial binaries inside a *copy* of the served root
  image instead of pushing them over the serial console on every boot.
- **`devcore-cp-scan.py`** — decode the `CP_LOAD_STATE` packets in a
  `drm/msm` GPU devcoredump.

Neither is device-specific beyond a3xx packet decoding; the payload recipe
works for any liveboot fixture.

## Why bake a payload

Liveboot serves a PocketFed OSTree root image read-only over USB
(`smoo-host`) and gives the guest a RAM copy-on-write layer. A trial that
needs a 22 MB `libgallium`, a 6 MB `eglretrace` and a trace file has two
options: push them over the UART console at roughly 5 kB/s — about 15 minutes
per boot, repeated after every board reset — or have them already in the
image. This does the second without modifying the image you already trust.

Measured on 2026-09-21: baking 33 files (36 MB) took 4.3 s including the
sparse copy of an 8 GiB image, against ~12 min of UART pushes for the library
alone, on a fixture that reset five times during the investigation.

### Where the payload goes

`/opt` in the deployment is a symlink to `/var/opt`, and the deployment
bind-mounts the **stateroot** var over its own:

```
/var  <-  /dev/mapper/smoo-root[/ostree/deploy/pocketfed/var]
/opt  ->  /var/opt
```

So the copy that matters is `ostree/deploy/<osname>/var/opt/<name>` inside the
image, and that is where `bake-payload.sh` installs. A copy written into a
deployment's own `deploy/<checksum>.0/var` is shadowed by the bind mount and
does nothing.

### Usage

```sh
sudo tools/adreno/bake-payload.sh \
    --src     out/google-sargo/pfroot.img \
    --dst     /var/tmp/trial/pfroot-adreno.img \
    --payload /var/tmp/trial/payload \
    --name    adreno
```

The contents of `--payload` become `/opt/adreno` in the guest, with a
`SHA256SUMS` written alongside them so the guest can prove the transfer:

```
[root@db410c ~]# cd /opt/adreno && sha256sum -c --quiet SHA256SUMS; echo $?
0
```

`--src` is opened read-only and never modified — the script refuses if
`--dst` already exists unless you pass `--keep`, and `--dry-run` prints the
plan without mounting anything. Keep the source image unchanged throughout the
copy. Serving it read-only with `smoo-host` is fine; the optional `fuser` check
only warns about open files and cannot guarantee the absence of writers.
`--name` must be one path component other than `.` or `..`. Run actual baking
as root; it loop-mounts the copy. The dry-run name regression needs no root:

```sh
bash tools/adreno/test-bake-payload.sh
```

### The export id changes with the path

`smoo-host` derives the export id from `hash(block_size, block_count,
"file:" + canonical path)`, so serving the baked copy changes the id that the
guest must ask for. The boot image carries that id as `rd.smoo.root=`, which
means a baked copy needs **both** halves updated:

```sh
smoo-host --product-id 0xBEE1 --file /var/tmp/trial/pfroot-adreno.img
tools/liveboot-db410c/build-initrd.sh ... --export-id <new id>
```

`smoo-host` only prints the id once a gadget attaches, which is a
chicken-and-egg with building the initrd it is needed in; derive it from the
path and validate the derivation by reproducing a known-good id for an image
you already have a working boot image for.

### Session helper

A payload usually wants a small `env.sh` beside it, sourced from the serial
root shell, holding whatever makes a run reproducible. For #80 that is the
greeter-session wrapper, because the workloads must run inside the live
phoc session rather than on the console:

```sh
greetrun() {
  runuser -u greetd -- env HOME=/var/lib/greetd \
    XDG_RUNTIME_DIR=/run/user/991 WAYLAND_DISPLAY=wayland-0 \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/991/bus \
    XDG_CURRENT_DESKTOP=GNOME "$@"
}
```

Resolve the actual user, runtime directory and Wayland socket on other
fixtures.

## Reading a GPU devcoredump

`/sys/class/devcoredump/devcd*/data` is YAML with the ringbuffer and the
submit's buffer objects appended as ascii85. The payload is a sequence of
u32s encoded most-significant byte first, so reading the decoded bytes as
little-endian dwords yields byte-swapped garbage and finds no packets at all.

```sh
python3 tools/adreno/devcore-cp-scan.py dump.devcore        # constant loads
python3 tools/adreno/devcore-cp-scan.py dump.devcore --all  # every CP_LOAD_STATE
```

The scanner respects YAML literal-block indentation, so section names such as
`bos:` and `registers:` cannot be mistaken for encoded bytes. Malformed or
incomplete dwords are reported as undecodable payloads; incomplete packet bodies
are skipped. Run its synthetic regression fixtures with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/adreno/test-devcore-cp-scan.py
```

It prints the dump's identity (`comm`, `cmdline`, `revision`, `rbbm-status`,
fences, `rptr`/`wptr`) and then every `CP_LOAD_STATE`, decoded into
`dst_off`, `state_src`, `state_block`, `num_unit` and `state_type`, with a
summary counting the fragment-stage and vertex-stage indirect constant loads
separately. On an a306 hang from this investigation the interesting line is

```
+0x0020a4 cnt=2 dst_off=16 SS_INDIRECT SB_FRAG_SHADER num_unit=32 ST_CONSTANTS src_addr=0x03082180
```

Two caveats, both load-bearing:

- The scan tests every dword as a candidate header rather than walking the
  packet stream, because a dumped buffer object need not start on a packet
  boundary. False positives are possible in pure-data payloads.
- A dump says what a submit *contained*, not which draw the GPU was executing
  when it wedged. There is no instruction pointer into an IB in the dump, and
  GPU execution is asynchronous.

Copy the dump out of `/sys` before reading it (reading `data` is fine;
*writing* to it deletes the dump), and clear it afterwards so the next hang
gets a fresh `devcd` node.
