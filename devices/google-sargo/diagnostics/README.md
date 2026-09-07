# Sargo suspend and voice acceptance

Use this checklist after deploying the ModemManager bearer-count correction and
81voltd lifecycle hardening. The [investigation](../modem-suspend.md) records the
failure and recovery. Record the USB developer-management sleep inhibitor and
cradle/cable conditions when comparing suspend tests.

## IMS status helper

[ims-state.py](ims-state.py) opens one fresh QRTR socket, binds its diagnostic
IMSA client, reads registration and service status, then closes the socket. It
does not place calls or change modem power, bearers or IMS settings. Each query
has a 10 second timeout; bound the whole invocation to 40 seconds.

Run `qrtr-lookup` on the phone before each session and after every boot or modem
restart. Select **service 33 (IMSA)** and use its current node and port. Node 0,
port 78 was observed during the investigation; the port is not a persistent
device identifier. Binding **0** returned valid results on that Sargo boot;
this is an observed working value, not a universal primary-subscription mapping.
Binding 1 accepted Bind but returned `InvalidOperation` for the status queries.
An error response is inconclusive about IMS registration.

From the directory containing the helper, substitute the discovered endpoint:

```sh
umask 077
evidence_dir=$(mktemp -d /var/tmp/sargo-acceptance-XXXXXXXX)
qrtr-lookup > "$evidence_dir/qrtr-before.txt"
timeout 40s python3 ./ims-state.py --node NODE --port PORT --binding 0 --raw \
    > "$evidence_dir/ims-before.jsonl" 2>&1
```

Run the helper anew for every snapshot. Separate qmicli bind/get processes do
not preserve the same QRTR diagnostic client through synthetic CIDs. Keep raw
responses, journals and cores private: they can contain subscriber identities,
numbers, addresses and process memory. The default helper output omits raw
packets, but decoded registration error text also needs review before sharing.

## Controlled rollout and test

1. **Coordinate installation and reboot with Sam.** Record the intended image
   digest and exact RPM builds, preserve the existing deployment for rollback,
   and stage both corrections together. Reboot at the agreed time, then verify
   the booted deployment and installed versions. A successful package build or
   staged deployment is not proof that the phone is running the corrected code.

2. **Capture a working baseline before each suspend cycle.** Create a private
   evidence directory as above; record local time with timezone, boot ID,
   `uname -r`, `rpm-ostree status`, and package versions:

   ```sh
   rpm -q ModemManager ModemManager-glib 81voltd libqmi libqmi-utils \
       libqrtr-glib NetworkManager calls callaudiod
   systemctl show ModemManager.service 81voltd.service \
       -p MainPID -p NRestarts -p ActiveState -p ActiveEnterTimestamp
   ```

   Save these outputs with the cycle ID and timestamp. Discover the current
   modem with `mmcli -L`; capture its JSON, all listed bearer JSON and voice
   call list using the current object IDs. Identify the internet and `ims`
   bearers by their properties, rather than assuming bearer 0 or modem 0.
   Record IMSA registration and voice/SMS availability with the helper. Establish
   that no call is active before proceeding.

3. **Sam initiates suspend and wake manually.** Agree on the cycle and wake
   method first. Record cable/power conditions, sleep inhibitors and advertised
   suspend mode. Normal unplugged validation requires disconnecting the USB
   developer management link, which holds `USB-developer-management-link`.
   An explicitly agreed inhibitor-bypassed test must be labelled separately.
   Confirm actual suspend entry and resume from kernel/systemd journals; shell
   command completion alone does not establish either event. Reconnect the
   management link after wake if needed.

4. **Capture wake recovery before intervention.** Repeat the baseline snapshots
   with new timestamps. Compare boot ID, daemon PIDs and restart counts; retain
   suspend/resume and ModemManager/81voltd/NetworkManager journals spanning the
   whole cycle. Evaluate these separate observations:

   | Observation | Required evidence |
   | --- | --- |
   | Suspend stability | Resume completed; no new ModemManager abort/core or unexpected daemon restart. |
   | Cellular data | Current registration, packet attachment and internet bearer state; record actual data connectivity separately if checked. |
   | IMS transport | The bearer with APN `ims` is connected and has an address. |
   | IMS voice | Successful IMSA Gets report `registered` and voice `available` over WWAN. Record SMS status separately. |

   Repeat fresh-socket IMS queries while recovery progresses and record the
   time to readiness. The 81voltd request deadlines bound daemon work; they are
   not a guaranteed carrier registration time. LTE data, NAS voice support,
   a connected IMS bearer and `EmergencyOnly=false` each fall short of proving
   IMS voice registration. Preserve a timeout, unavailable service or query
   error as its own result.

5. **Coordinate the real outgoing call with Sam.** Once IMS voice is available,
   Sam places the call to the agreed reachable phone. Record dialing, ringing,
   active and termination times and reasons. Both participants confirm speech
   is audible in both directions, then confirm hangup and an empty call list.
   Silent music playback does not establish telephony audio. Capture IMSA and
   service counters again after the call. Repeat the agreed suspend/wake/call
   cycles; report the number and conditions actually completed.

6. **Preserve failures before targeted recovery.** If any stage fails, save
   modem/bearer/IMSA snapshots, service and Calls journals, kernel suspend
   evidence and any new core with matching executable/build identifiers first.
   Record the failed cycle separately from a later recovered call. Choose and
   record any recovery action only after capture; establish that there is no
   call and that management access survives a cellular interruption. A manual
   reconnect, power transition or service restart invalidates that cycle as
   evidence of automatic recovery.

The package regressions exercise production lifecycle code and IMSD codecs with
a private D-Bus modem simulation and substituted QRTR transport. They verify
request ordering, cancellation, retries and stale-callback handling. They do not
model suspend hardware, modem firmware, carrier IMS registration or call audio;
the phone checklist supplies that acceptance evidence.
