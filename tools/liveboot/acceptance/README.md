# DB410c graphical acceptance add-on

Extra userspace for the disposable DB410c acceptance boot, layered on top of the
tracked `overlays/apq8016-sbc` overlay. It closes two host-side gaps from
`out/liveboot/db410c-20260914-supervision/12-acceptance-readiness.md`:

- **P1** is closed by the derived profile
  `profiles/apq8016-sbc-graphical.json`, which changes only the boot target
  (`systemd.unit=graphical.target`) and adds
  `systemd.wants=pocketfed-liveboot-cpu-acceptance.service`. `graphical.target`
  pulls `display-manager.service` -> `phrog.service` (greetd + `phoc` +
  `gnome-session --session=phrog`), so packaged phrog starts.
- **P3** is closed by this add-on's oneshot service, which runs the retained
  measured MSM8916 workloads on CPU0-3 and prints a
  `POCKETFED_CPU_ACCEPTANCE=` summary to `journal+console` for the liveboot
  runner's UART capture.

## Files

- `usr/libexec/pocketfed-liveboot-cpu-acceptance` — collects `smp-work` and
  `smp-coherency` output into `/run/pocketfed-liveboot/cpu-acceptance.json` and
  prints the console marker. Exits non-zero unless all four CPUs pass with the
  expected hash and the coherency diagnostic passes.
- `usr/lib/systemd/system/pocketfed-liveboot-cpu-acceptance.service` — oneshot
  unit, conditional on `pocketfed.liveboot`, ordered after the handoff reporter.

## Workload binaries

The two static ARM64 workloads are not tracked here; they are the retained,
already-built lab tools reused byte-for-byte and assembled into the generated
acceptance overlay at fixture-export time:

| Binary | sha256 | Source / build |
| --- | --- | --- |
| `usr/libexec/pocketfed-liveboot/smp-work` | `3b1a25c21801708e04464954efb10b0723b92a07efc4f91cdd08b85316536ab5` | `pocketboot/tools/smp-work.c`, `aarch64-linux-musl-gcc -Os -static -s` |
| `usr/libexec/pocketfed-liveboot/smp-coherency` | `c9f5b66ae145b757ae277a80e9fc746b582badb40b9af8cf2cf5cc2fce02a9f0` | `pocketboot/tools/smp-coherency.c`, same toolchain |

Both are the binaries recorded in
`02b-baseline/20260914-agent2-baseline/artifacts/kexec-coherency-recovery/`.

## Generating the acceptance overlay

The overlay passed to `prepare-fixture.py` is assembled under the generated
artifacts directory (never committed):

```sh
overlay=out/liveboot/db410c-20260914-supervision/14-graphical-acceptance/overlay
mkdir -p "$overlay"
cp -a tools/liveboot/overlays/apq8016-sbc/. "$overlay/"
cp -a tools/liveboot/acceptance/apq8016-sbc/. "$overlay/"
mkdir -p "$overlay/usr/libexec/pocketfed-liveboot"
cp <smp-work-v2> "$overlay/usr/libexec/pocketfed-liveboot/smp-work"
cp <smp-coherency-v1> "$overlay/usr/libexec/pocketfed-liveboot/smp-coherency"
```

The fixture manifest then records every overlay file hash, including the two
binaries, so the immutable fixture carries their identity.
