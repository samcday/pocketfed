# DB410c / A3xx Mesa investigation: handover to Claude

Prepared 2026-09-23. This is a continuation report, not a claim that the original
Mesa hang is fixed. No new GPU workload was run while preparing this handover.

## Start here

Sam wants the next session to **stay on the Mesa investigation**. Three Linux
recovery/runtime-PM fixes emerged during this session; Sam will review and
prepare their upstream submission. They are useful test infrastructure, but
continuing to polish kernel patches is not the next investigative objective.

The immediate question is: why does the reduced clear + rounded-clip draw hang
with indirect fragment constants in an ordinary batch, while direct constants
or flushing after each draw works? We have a reliable reproducer, matched
diagnostic libraries, verified crash dumps, and pixel-checked passing controls.
The underlying hardware/firmware/driver mechanism is still unresolved.

**Communication preference:** Sam communicates with Rob Clark entirely in his
own words. Supply measurements, explanations and qualifications. Do not write
or post an upstream reply on Sam's behalf, or treat the existing local reply
draft as approved text. Sam already linked the detailed PocketFed issue in the
Mesa discussion. No new Mesa GitLab comment, upstream MR, mailing-list patch,
merge, or flash was performed in this session.

Read this report, then these maintained summaries:

1. [Hardware ledger](hardware-20260923.md): definitive B1–B13/t01–t30 results.
2. [Rob follow-up audit](rob-followup.md): controls, upload sizes, corrected claims.
3. [Recovery audit](recovery-clocks.md) and [VBIF audit](vbif-halt.md): kernel findings.

Public work:

- [PocketFed issue #80](https://github.com/samcday/pocketfed/issues/80): historical investigation.
- [Mesa issue #12634 / Rob's reply](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/12634#note_3674373).
- [PocketFed PR #92](https://github.com/samcday/pocketfed/pull/92): this branch's diagnostics and evidence; **draft**.
- [PocketFed PR #89](https://github.com/samcday/pocketfed/pull/89): corrected devcoredump decoder and payload tooling.
- Linux [#5](https://github.com/samcday/linux/pull/5), [#6](https://github.com/samcday/linux/pull/6), [#7](https://github.com/samcday/linux/pull/7): open, ready for human review, unmerged.

The historical #80 summary says things such as “root cause found” and “kernel
and firmware are out.” Those statements exceed the evidence now established.
Retain the underlying observations, not those categorical interpretations.
Likewise, older local README/runbook sections describe B7 and later controls
as pending. They are completed. This report and the maintained hardware ledger
supersede that historical planning text.

## Workspace and current device state

Host checkout:

```text
/var/home/sam/.codex/worktrees/658f/pocketfed
branch: codex/adreno-rob-followup
remote: https://github.com/samcday/pocketfed.git
hardware-results commit before this documentation update:
93672feb8a30e32cddce569de448557bc0315782
```

Local evidence root, referred to as `OUT` below:

```text
/var/home/sam/.codex/worktrees/658f/pocketfed/out/adreno-rob-20260923
```

It is intentionally ignored by Git. Raw logs, binary libraries, device dumps,
images and trial archives remain local. Commit source and concise evidence only.
The report itself is tracked in PR #92. Follow the checkout's `AGENTS.md`: use
focused branches/PRs in `samcday`, preserve unrelated work, no default-branch
push or merge, and no external-upstream PR without explicit authorization.

Read-only host verification during handover preparation confirmed:

- `fastboot devices`: **bc72e60**, Android Fastboot.
- UART: `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0`,
  currently resolves to `ttyUSB0`; **115200 8N1**.
- UART has no owner; no `smoo-host` process is running.
- Last hardware session ended by orderly reboot to resident fastboot. Nothing
  was flashed. The root server and UART were released afterward.
- Do not use another FTDI adapter or a historical `ttyUSB` number by assumption.
- Device nodes and USB were invisible inside Codex's restricted sandbox;
  authorized host-level read-only checks confirmed them. A sandbox-only empty
  fastboot list is not evidence that the board has disappeared.

`OUT/CURRENT-STATE.json` records the last session and fixture identity. Recheck
live state before booting. No previous task/session handle or PID is reusable.
Start new logs at **B14**, new trial labels at **t31**, or use a distinct session
prefix; do not overwrite B1–B13 artifacts.

PR #92's pre-handover head had all eight GitHub Actions checks successful and a
successful CodeRabbit status. The three kernel PRs also had successful review
statuses, but these are not human approval or substitutes for hardware testing.
Documentation updates may trigger a new CI run; inspect its actual state.

## Rob's questions and the measured answers

Rob observed that a5xx+ QRISC firmware handles direct and indirect loads alike
apart from the source address, suspected the added wait, requested constant
upload sizes and a devcoredump, suggested !44620 with assertions enabled for
kill/discard-related failures, and suspected a clock vote preventing recovery
power cycling. His newer-generation firmware observation is a hypothesis for
A3xx, not a verified description of A3xx microcode.

### CPU preparation versus upload transport

The matched Mesa 26.2.2 hardware matrix is complete:

| Arm | Mode | Minimal clear + draw | Full R3 / pixels |
| --- | --- | --- | --- |
| stock indirect | sysmem | Hangs | Not repeated without flush in this matrix |
| stock indirect | sysmem,flush | Passes | Passes, reference pixels |
| direct-no-wait | sysmem | Passes | Passes, exact reference pixels |
| direct-wait | sysmem | Passes | Passes, exact reference pixels |
| wait-only, still indirect | sysmem | Hangs | Not run |
| checked wait, still indirect | sysmem | Hangs, no reported prep error | Not run |
| fresh-source, still indirect | sysmem | Hangs | Not run |
| stock-asserts | sysmem | Hangs, no assertion | Not run |
| !44620 / sched | sysmem | Hangs, no assertion | Not run |

Direct controls are logging-free. Full-trace completion was tested separately
with and without snapshot readback. No new hangcheck and matching pixels were
required; process exit zero alone was not accepted as success.

The specific added `fd_bo_cpu_prep(bo, NULL, FD_BO_PREP_READ)` is neither needed
for the observed direct-upload passes nor sufficient to rescue indirect loads.
The checked control propagates existing fence-wait errors and aborts on nonzero
prep; it still hangs without such an error. A zero return can mean an idle fast
path, not that a blocking wait actually occurred. This does not rule out
GPU-side ordering within a submission, visibility issues, or all synchronization
bugs. It does not independently prove the same result for SuperTuxKart.

Direct here means CPU-copying the values into the `CP_LOAD_STATE` packet body.
The GPU command processor still fetches that stream and loads the constant
file. Indirect supplies a GPU address of another buffer. Do not describe direct
as CPU writes straight into hardware constant RAM, or as removing all GPU DMA.

**The strongest counterexample to “indirect DMA never works” is stock plus
`sysmem,flush`: it retains indirect constant loads and renders correctly.**
`flush` calls the context flush after each draw, changing batch/submit boundaries
and surrounding commands. It does not convert constants to direct loads and is
not simply a CPU-cache flush. GPU command fetching itself already establishes
some working GPU-initiated memory access; different paths can have different bugs.

The fresh-source experiment copies the entire 16-KiB source to new BOs and
retains the same offsets, sizes and indirect packets. VS and FS use distinct
new BOs. Both captured clones match, including zero tails. The original UBO
contents were not captured, so dump-only original-to-copy equality is unproved.
The run changes allocation, aliasing and timing as well as source freshness;
it weakens a simple reuse hypothesis but does not eliminate cache/visibility.
Its saved RPTR equals WPTR, unlike the usual stock failure: same hang outcome
does not imply an identical stall point.

### Compiler MR !44620

Matched O2/assertions-enabled baseline and MR builds both hang on separate fresh
boots, without assertions. Their captured fragment shader bytes are identical
(13,792-byte extracted range). The reduced shader has no kill/discard/demote,
so it does not exercise the MR's cross-block kill/bary.f case. All five captured
VS/FS pairs were compiled in the host harness; no relevant assertion fired.
Two existing IR3 tests passed on each host build.

This rules out that specific compiler condition for this reproducer, not every
scheduler issue, shader, or application mentioned in the upstream issue.
Use `debugoptimized` plus `b_ndebug=false`, not `buildtype=debug`: the latter
enables Mesa draw markers which insert extra `CP_WAIT_FOR_IDLE` packets and
confound this investigation. The tested assertion builds have `MESA_DEBUG=0`.

### Requested sizes, bounds and dumps

Rob asked for **uploaded constant size**, not shader binary size:

| Stage | DST_OFF | NUM_UNIT | Upload | Destination |
| --- | --- | --- | --- | --- |
| VS | 16 | 16 | 128 bytes / 32 dwords | vec4 8–15 |
| FS | 16 | 32 | 256 bytes / 64 dwords | vec4 8–23 |

For A3xx `ST_CONSTANTS`, one unit is two dwords/eight bytes. Mesa passes regid
32 and encodes `DST_OFF=regid/2`. Both source ranges start at UBO byte 576 in
the reduced test. The GL binding is 160 bytes, so FS reads 96 bytes beyond the
binding while remaining within the 16-KiB BO. This is a separate bounds lead,
not proof of the hang's cause. Direct also copies the same upload length.

The old proposed Patch C rounds a clamp upward to an upload unit and therefore
does not generally prevent reads past a nonaligned binding. A proper treatment
must address a partial final unit and allocation padding. Do not silently mix
Patch C into transport/ordering controls.

Useful local handoff attachments:

| Path under OUT | Bytes | SHA256 |
| --- | ---: | --- |
| `hardware/b2-t11-stock.devcore` | 94189 | `70e34029ab2114569777bd71adc1369830eff1d900912af1b07dcea1501a2ef2` |
| `upstream/a306-minimal-pair.trace` | 218166 | `e6521177868fd693fcbd2faf684e53cb634c11dc332872194db51e9aa12aa397` |
| `upstream/b10-minimal-pair-sysmem.devcore` | 94309 | `ae7e58f0f454c3b8f2cc6937fa3d3ffe05a36cc37d2987eb6493b16397e348aa` |
| `hardware/pixels/t08-0000006260.png` | 102197 | `2d34c84ae83f9d0814880c0d062bf664572f191a93e6cb6beb02889ce8e36775` |

The representative frame is 1280×688 with real GTK gradient/text content.
Direct-no-wait and direct-wait frames match it exactly. `upstream/reply-draft.md`
contains an older synthesis and attachment checklist; it is **not approved
communication** and includes some superseded status wording.

## What earlier sessions already tested

Consult original evidence before repeating these. Earlier trials often shared
a boot after recoveries and included logging, so they are weaker controls than
this session's fresh-boot, logging-free comparisons.

- Removing the preceding clear or splitting clear/draw across submissions
  avoids the reduced failure. Preserve the exact scissor/render state when
  reproducing; a generic standalone UBO test may simply miss the trigger.
- FS-only direct conversion worked in older trials while VS stayed indirect.
  This does not establish all VS loads are safe in other workloads.
- Splitting the 256-byte indirect FS load into two 128-byte indirect packets
  still hung; the intended packets were logged. Do not revive a universal
  128-byte maximum-transfer explanation without new distinguishing evidence.
- `HLSQ_CONTROL_0_REG` LAZYUPDATEDISABLE (`0x10000000`), CHUNKDISABLE
  (`0x04000000`), and SINGLECONTEXT (`0x80000000`), tested separately, still hung.
- Earlier WFI/HLSQ_FLUSH rearrangements/removal did not fix the hang. The kernel
  also emits HLSQ_FLUSH + WFI at submit end. Exact packet placement matters:
  failure of those variants does not rule out every barrier, but a generic
  “add WFI near HLSQ flush” experiment is not new.
- Patch A disables fragment UBO-to-constant lowering. Historical DB410c GTK
  tests passed in sysmem and GMEM. It was insufficient for the later A5
  SuperTuxKart case; do not merge those two workloads into one proof.
- B2/direct-all-mappable-stages had an A5 SuperTuxKart pass reported by Sam.
  This session did not rerun that benchmark or establish general performance.
- B2 does **not** convert every buffer-backed constant load: shader constant
  data in `FD_BO_NOMAP` buffers takes its indirect fallback.

Relevant historical comments: [register audit](https://github.com/samcday/pocketfed/issues/80#issuecomment-5757144553),
[knob trials](https://github.com/samcday/pocketfed/issues/80#issuecomment-5757485832),
[earlier WFI trials](https://github.com/samcday/pocketfed/issues/80#issuecomment-5756571257).
Treat their broad mechanism language as hypotheses. A post-hang register snapshot
does not prove no shader wave ever ran or identify the causal packet.

## Prioritized Mesa leads

These are proposed experiments, **not completed work**. Choose a small matched
set with a clear discriminator, inspect its generated stream on the host, and
then spend board time. Do not rerun the entire completed matrix.

1. **Identify what the working submit boundary supplies.** Compare the real
   clear + draw stream with the split-submit case, including kernel epilogues
   and Mesa restore/state setup. Look for state invalidation, events, cache
   operations or state re-emission that distinguish them. Then keep indirect
   constants and test a narrowly placed operation. Audit the old WFI attempts
   first. Record why the new placement/operation is different. CPU prep on
   previous fences is not equivalent to ordering current GPU commands.
2. **Separate packet mode from memory location and command layout.** Direct
   copies values and enlarges the command stream. An indirect load from known
   command-buffer-like storage, and/or a carefully padded indirect control,
   could discriminate source visibility from SS_DIRECT mode or layout/timing.
   This needs correct relocation, lifetime, alignment and packet framing; raw
   payload must not accidentally be executed as commands. Fresh BO alone has
   already failed. Equal byte count alone does not make execution timing equal.
3. **Reduce the context/state dependency.** Retain the failing shader and UBO
   while varying only the preceding operation or relevant constant-window state.
   Distinguish a scissored clear's draw/state effects from just having two
   operations in a batch. Avoid recompiling away the pushed FS range by accident.
   Host shader hashes and packet diffs can establish that the trigger survived.
4. **Source/destination alignment and bounded size sweeps**, if a specific
   source/register observation motivates them. Keep payload, shader and prior
   draw fixed. Existing split-upload failure rejects one size-limit theory;
   it does not characterize every alignment/window edge case. Keep the binding
   over-read investigation separate and use initialized padding for controls.
5. **Vendor usage / errata evidence.** Inspect A3xx blob captures or relevant
   firmware/driver code if available. Determine whether and when it uses
   indirect ST_CONSTANTS and which surrounding operations it emits. An absence
   in a small capture is not proof of a silicon-wide prohibition. A5xx firmware
   behavior is a clue, not A3xx evidence. Other A3xx devices would establish scope
   later; they are not needed before useful DB410c work.

Suggested next board session: choose stock or all-three kernel deliberately;
establish the relevant baseline and passing reference under that exact kernel,
then run one host-audited Mesa diagnostic. All-three has passed PM/rendering,
but the original negative reproducer was last demonstrated with **two fixes
combined (B12)**, not with all-three (B13). Do not describe an unrun combination
as tested. Keep runtime-PM policy and display state explicit and matched.

## Kernel findings: completed, leave submission to Sam

| PR | Defect and fix | Hardware evidence |
| --- | --- | --- |
| Linux #5 | After reset, normal A3xx suspend tries to drain a reset ring, fails before clocks turn off; recovery ignores failure and resumes anyway. Use generic clock shutdown in A3xx recovery while retaining resume/init. | Six fresh stock boots each leaked one enable/prepare ref on all six bulk clocks. Candidate B9 survives two intentional recoveries without growth or stale-ring timeout; later rendering matches reference. |
| Linux #6 | A306 suspend polls six VBIF halt bits although only three respond. Select three bits for this GPU. | Fresh stock B10 has idle checks succeed, request readback `0x7`, ack `0x70007`, poll mask `0x3f`. Downstream source agrees. Mask-only B11 powers OXILI off, zero clocks, 20 successful generic suspend/resume returns, matching frame. |
| Linux #7 | Resume without work leaves hardware init pending; suspend compares reset hardware ring state with stale software state. Skip ring idle while `needs_hw_init`, retain VBIF halt. | All-three B13: three no-work cycles with flag 1 pass; subsequent full frame matches and 14 initialized PM cycles with flag 0 pass. |

B12 confirms #5 + #6 together: original Mesa hang remains, recovery returns
success, idle suspend succeeds and clocks return to zero. The compositor later
crashes when waking the blanked display; service restart restores reference
rendering. None of this proves the historical whole-board resets share the
same cause. #5 does not repair votes already leaked earlier in a boot.

All kernel PRs target `samcday/linux:codex/adreno-recovery-base-7.3-rc3`:

| PR | Head branch | Reviewed-session head |
| --- | --- | --- |
| #5 | `codex/adreno-recovery-clock-balance` | `bfb6f2641984015f441d45b440466faaf10ec056` |
| #6 | `codex/adreno-a306-vbif-mask` | `f31639c6ff5c919167da7ba3bf69baa9e40ad139` |
| #7 | `codex/adreno-uninitialized-idle` | `a1c6ad243d0356af64d57d1eca35a19a842f6e80` |

Candidates are unsigned external exact-Fedora-ABI modules without module BTF.
Actual loading was verified from the live module note, not just rootfs
`modinfo`. No other A3xx hardware or injected init-failure path was validated.

## Booting the existing fixture without flashing

`OUT/fixture-checked/pfroot-rob.img` is the immutable eight-arm root. Export ID
**3863380309**, 512-byte blocks, SHA256
`006e8196cf81a419c51d9e52e32a9edaa38b06edb8a5eedfa68841161a660114`.
The guest writes to a RAM COW layer. Preserve the origin; all guest changes and
`/run` captures disappear on reboot unless pulled first.

| Choice | Boot image relative to OUT | Boot SHA256 | Live MSM build-ID note SHA256 |
| --- | --- | --- | --- |
| Stock | `fixture-checked/liveboot-a3chk.img` | `3219d414163a7501d529128fe78ec8102d2590165e28195e19edb5dfaf9d6bd1` | `d0c1a71c7555e24ea32914c70cd8fd654bb35bf4141b63eae9a657d98cf19091` |
| Recovery only | `kernel-fixture/checked/liveboot-a3cfix.img` | `34e69c0cee750576e304a46da53eb62b5d71ae8b4f8c8a8ff00848260c09761d` | `26a44dfeccef1cc8b948b6a68983334760c61831783faae4a907aa37e8cad56b` |
| All three | `kernel-fixture/all-three/liveboot-a3all3.img` | `f2025bc6f307067abc9e0cc49c3c604618cb528ff2fc0e9e4d30db3f91fabce8` | `50790d5fbfce63bcba1f2620eba25f1ed4d763bed04e4fd8c19ec66523d37fbf` |

Mask-only and two-fix boots are in `kernel-fixture/mask-only/` and `combined/`;
their manifests hold exact identities. All use the checked root above.
The candidate packaging preserves Image, DTB and the other 730 initramfs CPIO
entries, changing the MSM module and boot marker. Do not unload live MSM.

Start continuous UART capture first, then a new owned server with its own log:

```sh
/var/home/sam/src/smoo-liveboot/target/release/smoo-host \
  --product-id 0xBEE1 \
  --file /var/home/sam/.codex/worktrees/658f/pocketfed/out/adreno-rob-20260923/fixture-checked/pfroot-rob.img
```

From positively confirmed fastboot, choose **one** boot image:

```sh
fastboot -s bc72e60 boot \
  /var/home/sam/.codex/worktrees/658f/pocketfed/out/adreno-rob-20260923/kernel-fixture/all-three/liveboot-a3all3.img
```

That command is a future example, not something run during handover. Restart
the owned root server between boots, only after fastboot is confirmed. Never
stop it while the guest relies on it. Source-image path participates in the
export ID: moving/copying it requires a new ID and matching boot cmdline.
Pocketboot cmdline limit is 511 bytes; existing boots are 508–509 bytes.

B4 failed before init with ext4 checksum errors while the host origin hash was
unchanged. B7 stalled after automatic login before a shell prompt. Neither ran
its proposed Mesa test. Later boots completed those tests successfully. These
fixture failures are not additional GPU results. If shell/serial recovery fails,
preserve logs and ask Sam for a physical reset to fastboot; do not spin through
unbounded resets or equate echoed commands with execution.

## UART, guest readiness and evidence transfer

Preserved UART tools are in `OUT/handover-support/uart/` (copied from the working
re-provision fixture). They use a persistent daemon and JSON-line FIFO, avoiding
multiple serial readers. `uart-console.py` holds an exclusive serial lock and
logs all bytes. For example, in a separately owned long-lived host process:

```sh
python3 out/adreno-rob-20260923/handover-support/uart/uart-console.py \
  --device /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0 \
  --log out/adreno-rob-20260923/hardware/uart-b14.log \
  --fifo /tmp/adreno-b14.fifo
```

Use `uart-run.py --fifo ... --log ... --timeout 45 'guest command'` to send a
command and wait for a split completion marker. **Its host exit zero means a
marker arrived, not that the guest command succeeded**: inspect `__rc=`.
`uart-pull.py --fifo ... --log ... --src /run/file --dst /host/file` transfers
xz/base64 and verifies its hash. Use controlled simple paths; this helper
interpolates the guest source path into a shell command. Avoid competing readers.
UART transfer is about 5 KiB/s; bake large libraries instead of retransmitting
them each boot. `uart-push.py` is also preserved; consult its help before use.

Guest preflight, once an actual root shell responds:

```sh
uname -r
cat /proc/sys/kernel/random/boot_id /proc/uptime /proc/cmdline
findmnt -n -o SOURCE /
(cd /opt/adreno && sha256sum -c SHA256SUMS)
(cd /opt/adreno-rob && sha256sum -c SHA256SUMS)
sha256sum /sys/module/msm/notes/.note.gnu.build-id
. /opt/adreno/env.sh
id greetd
ls -l /run/user/991/bus /run/user/991/wayland-0 /tmp/.X11-unix/X0
ps -o pid,user,args -C phoc
cat /sys/kernel/debug/dri/0/state
```

Expected kernel: `7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46.aarch64`; command
line root export 3863380309, chosen marker, `rd.smoo.max_io=16384`. Record actual
runtime-PM policy, clocks and kernel errors. Candidate module rootfs metadata
can still describe stock; the loaded module-note hash is the check that matters.

Display service is **phrog.service**, not an assumed standalone greetd service.
The session user is greetd, UID 991. `greetrun` from `/opt/adreno/env.sh` sets
session environment; eglretrace is X11-only and uses existing Xwayland `:0`.
Require active scanout (`enable=1 active=1`) before a measured run. A working
wake request is:

```sh
greetrun gdbus call --session --dest org.gnome.ScreenSaver \
  --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.SetActive false
```

Verify PID and scanout afterward. Waking after a hang can expose a compositor
crash. If service restart is needed, record it and wait for readiness before
replaying; “unable to open display” before Gallium loads is a setup failure.
The attempted IdleMonitor.ResetIdletime method does not exist.

The historical trial helpers are preserved as `OUT/handover-support/`
`trial-functions.json` and `trial-functions-pixels.json`: their `send` string
creates `/run/adreno-trials.sh`, sources it and prints a hash/completion marker.
They record loaded process maps/environment, before/after clocks/PM/dmesg,
retrace output and compositor state, with a 45-second replay timeout. Read them
before reuse; require `captured=1` or equivalent verified loader evidence.

## Replay and pass/fail criteria

Guest arms: `/opt/adreno-rob/{stock,wait,direct-no-wait,direct-wait,wait-checked,`
`fresh-source,stock-asserts,sched}/libgallium-26.2.2.so`.
Full hashes are in `OUT/fixture-checked/fixture.json`, the baked manifests and
`controls/` archives. Do not mix Mesa 26.2.2 overrides with 26.2.3 loaders.

Before launch, check `LD_LIBRARY_PATH=<arm> ldd -r /usr/lib64/libEGL_mesa.so.0`.
The generic `libEGL.so.1` is only the GLVND dispatcher. Confirm actual runtime
maps too. Keep loader/per-upload logging out of timed comparison runs.

Minimal replay (choose arm and mode explicitly):

```sh
trial_arm=stock
trial_mode=sysmem
greetrun env -u LD_PRELOAD -u IR3_SHADER_DEBUG -u LIBGL_ALWAYS_SOFTWARE \
  -u FD3_FS_NO_PUSH_UBO -u FD3_FS_CONST_DIRECT \
  DISPLAY=:0 LD_LIBRARY_PATH=/opt/adreno-rob/$trial_arm \
  MESA_SHADER_CACHE_DISABLE=true FD_MESA_DEBUG=$trial_mode \
  /opt/adreno/at/usr/bin/eglretrace /opt/adreno-rob/a306-minimal-pair.trace
```

No `-w` (it keeps the application open). The reduced trace already contains
clear 6065, instanced draw 6108, swap 6248; do not apply old full-trace ignore
lists again. Full trace is `/opt/adreno/r3.trace`, SHA256
`37c13ce2a683153db84a63310e79fb46593e5462bc78035db3519d33ab0a683e`.
eglretrace SHA256 is
`3d5e91c72f52e7b60541e2119656c4fadf6db12c0463216cdaac8561002563f3`.

For correctness after a passing minimal test, replay full R3 with
`--call-nos -s /run/user/991/adreno-rob/t31-` after creating that directory as
greetd. Expect call-6260 PNG; compare decoded pixels to the reference, not just
file existence. Keep no-readback completion and readback runs distinct because
readback adds synchronization. Avoid unnecessary stock GMEM negatives: earlier
ones hard-reset the board. Sysmem is the useful controlled initial mode.

For each measured run preserve boot ID, arm/library hash, actual loaded maps,
clean environment, exact input, PM/display state, launch/end uptime, exit or
signal, new hangchecks, pre/post fences and clocks, compositor PID, and any dump.
After a hang, matching fences can be software retirement during recovery; an
exit-zero retracer can still have hung the GPU. Clock-count changes and timeouts
need separation from the original Mesa failure. Use fresh boots for decisive
negative comparisons, especially with stock kernel recovery leaks.

Capture the current `/sys/class/devcoredump/devcd*/data` to a labelled `/run`
file, hash it, pull it, verify host hash, then acknowledge that specific old dump
before another hang so it cannot masquerade as new evidence. Devcoredumps expire.
`hangrd` needs a reader attached before the hang; opening it afterward can yield
only a header. Pull all useful `/run` evidence before reboot.

`OUT/hardware/analysis/extract-trial-evidence.py` verifies tagged UART base64
archives against a guest SHA and restricts extraction paths. It requires the
documented Bxx/Txx markers; do not assume an arbitrary UART transcript fits it.
GPU debug register reads and clock-summary reads may wake hardware/providers;
take passive PM/clock snapshots first and keep measurement order consistent.

## Build and decode resources

| Location | Purpose / caveat |
| --- | --- |
| `/tmp/a3xx-rob-20260923` | AArch64 O3 transport controls, saved `fd3_emit.<arm>.c`, Mesa source, existing build and logs. Current source is modified; directory name is not proof of baseline. |
| `/tmp/a3xx-sched-board-20260923` | Matched O2/assertions-on stock/MR ARM builds. Saved libraries are authoritative; inspect current source. |
| `/tmp/a3xx-wait-checked-20260923` | Checked-wait source, build, original file copies, ABI results. |
| `/tmp/a3xx-fresh-source-20260923` | Native/ARM fresh-source builds and validation. |
| `/tmp/mesa-sched-44620` | Native drm-shim harness, all extracted GLSL, RD/cff streams, saved variants; current source/install was wait-only. |
| `OUT/host-evidence.tar.xz` | Durable saved native harness/shaders/streams/logs if scratch disappears. |
| `OUT/controls` | All eight compressed AArch64 Gallium libraries. |
| `OUT/board-validation`, `fresh-source-validation`, `wait-checked-validation` | ABI and host validation evidence. |
| `OUT/board-shader` | Extraction, disassembly and hardware/host shader equality evidence. |
| `OUT/handover-support` | Preserved UART tools, trial helpers, fixed decoder, build configuration/control sources. |

Mesa release 26.2.2 tag commit:
`3281a69a8bfd9f997e91c15ed0e6290cae12dd32`; source tar SHA256
`eeb29ca7e56cfaa8e8a79538dcf834e3b18e501c31bef5145e959ea437cc4216`.
Saved !44620 has commits `96a8da8d8de07b2a58e10b8d206401436c6ececc` and
`3bab7e568ef5c3863f9cda9b600f9e67448d25bf`. Do not silently substitute later MR
revisions when interpreting this result.

Existing Fedora AArch64 builder image: `localhost/mesa-freedreno-build:f46`.
Inspect container availability/runtime and mount conventions before invoking;
the build scripts expect their scratch directory at `/w`. Reuse dependencies,
but copy to isolated scratch and apply a known diagnostic to a known baseline.
Never build concurrent variants in the same writable source/build tree.

Preserved Meson `cmd_line.txt` contains the full Fedora-compatible setup:
`platforms=x11,wayland`, `glx=dri`, `glvnd=enabled`, EGL/GBM/GLES enabled,
freedreno-only Gallium, msm KMD, no Vulkan/LLVM. These loader options matter;
earlier incomplete builds lost Fedora's required `loader_dri3_*` exports.
Typical incremental target inside that configured ARM environment:

```sh
ninja -C /w/build -j16 src/gallium/targets/dri/libgallium-26.2.2.so
```

Strip/copy into a uniquely named arm, record SHA, check AArch64 ELF, soname,
exports and EGL/GLX/GBM resolution. Do not install over system Mesa. O3 transport
arms have assertions off/MESA_DEBUG=0; O2 scheduler arms have assertions on/
MESA_DEBUG=0. Compare within a matched set, not across optimization changes.

Host shim: `FD_GPU_ID=307` selects chip 3.0.6.0. It does **not execute GPU work**.
It is useful for normalized packet/payload and shader comparison only. See
`OUT/host-validation.md` and `/tmp/mesa-sched-44620/tools/README.md`. The host
RD instrumentation patch compensates for legacy A3xx ringbuffer dumping and
shim relocations; it is separate from board controls. `cffdump` needs the added
RD_GPU_ID section on these files; the harness has `add-rd-gpuid.py` for that.
Use a new output name: `run-variant.sh` deletes its selected output directory.

The corrected `devcore-cp-scan.py` is preserved under `OUT/handover-support/`;
its source is PR #89. It stops Ascii85 decoding at YAML literal-block boundaries.
The previous decoder consumed section labels and falsely reported overflow.
Encoded words are big-endian Ascii85 words that need correct conversion to the
little-endian BO data. Never infer memory corruption from the old parser error.
Packet presence in a dump does not identify the exact executing/causal packet.

Relevant Mesa source: `a3xx/fd3_emit.c` (`fd3_emit_const_user/bo`),
`a3xx/fd3_program.c` (shader buffer/cache/state), `ir3/ir3_const.h` and
`ir3_nir_analyze_ubo_ranges.c` (pushed ranges), `freedreno_draw.c`
(`fd_draw_vbo_dbg` calls flush), and A3xx register XML. Also inspect kernel submit
epilogues when comparing complete streams, without expanding kernel-patch scope.

## Adding new payloads and closing each session

For a large new library, prepare a **new copy** of the root while the board is
in fastboot. `OUT/fixture-checked/prepare-fixture.py` and `bake-payload.sh` show
the recipe; the preparation script refuses existing output intentionally.
Adapt into a new fixture directory with new names rather than editing the
preserved checked fixture or calling `--keep` on a served image.

OSTree `/opt` is backed by the stateroot's `/var/opt`; payloads must be baked
there, not merely into a deployment's apparent `/opt`. Recompute export ID from
absolute file path, block size and block count; rebuild matching boot cmdline;
verify its length and hashes; run read-only filesystem checks and guest checks.
Use the preparation script's implementation, which checks a known export ID.

When ending a hardware session: stop only owned probes, restore changed service
and power policy as recorded, capture/pull evidence, request orderly bootloader
reboot, verify fastboot, then stop the owned root server and release UART.
If reboot fails, preserve the server/log until physical reset is resolved.
Update `CURRENT-STATE.json` with real state and ownership, never merely planned
state. `seal-artifacts.py` hashes completed local artifacts, excluding root
images (their hashes are in fixture manifests) and active logs. Verification
against an existing seal should precede resealing old evidence.

The three published trace helpers have scoped cleanup and passed 12 local
normal/signal/error tests plus Bash syntax/ShellCheck. Their instruction-offset
probes are guarded for exact module hashes: do not transplant offsets into a
different binary. Hardware captures have zero recorded probe misses/buffer loss.
They are available if needed, but kernel probing need not accompany every new
Mesa experiment or add timing noise to the next matched comparison.

The desired next outcome is one discriminating Mesa result with a verified
stream and preserved hardware evidence, followed by a short factual explanation
Sam can use in his own conversation with Rob.
