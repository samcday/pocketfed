# Reusing upstream multi-SIM work

Research for [PocketFed #58](https://github.com/samcday/pocketfed/issues/58),
14 September 2026. This note tracks upstream reuse and coordination; it does not
propose an independent PocketFed telephony architecture or establish DSDS support.

## Funded effort and public progress

[NLnet's Dual SIM for Mobile Linux](https://nlnet.nl/project/Linux-MultiSIM/)
lists a March 2026 start and explicitly covers modem support, Phosh, GNOME Calls
and Settings, including subscription choice for calls, messages and data.

The [Commons Fund FAQ](https://nlnet.nl/commonsfund/faq/) explains that grants are
paid after agreed milestones are achieved. The detailed plan is established in
the project's agreement, as described in the
[applicant guide](https://nlnet.nl/commonsfund/guideforapplicants/); the public
award page is not a progress dashboard.
The start date alone does not establish elapsed engineering effort, completed
milestones or the project's specific delivery deadline.

There is public evidence of ongoing design work beyond the award page. Phosh's
[30 July mobile-data article](https://ev.phosh.mobi/blog/mobile-data-use/) links
the NLnet dual-SIM project and credits a Sam Hewitt mockup to ongoing multi-SIM
work. It separately describes mobile-data-usage monitoring by Gotam as work
funded by the Phosh association. Do not conflate that monitoring service with
the NLnet modem/subscription implementation.

[Calls #747, Multi-SIM Calling](https://gitlab.gnome.org/GNOME/calls/-/work_items/747)
was opened by Sam Hewitt on 6 July 2026. It proposes incoming-call line labels,
a dial-pad line selector, and a chooser when dialing from contacts or recents.
Its [design commit](https://gitlab.gnome.org/Teams/Design/app-mockups/-/commit/d851823f854434e328d656b87df5139ea1c040b6)
is also dated 6 July. The issue and association article strongly suggest a shared
design effort; the public material does not establish whether this issue is a particular
contractual grant deliverable.

## Reusable code and design

| Item | State at inspection | Relevance |
| --- | --- | --- |
| [GNOME Settings !2867](https://gitlab.gnome.org/GNOME/gnome-control-center/-/merge_requests/2867) | Primary-SIM-slot selector merged 9 February 2026; proposal began October 2024. Present in the 50.0 release and current main. | Audit the existing selector before writing a new one. Selecting one active slot is distinct from simultaneous standby and independent voice/SMS/data defaults. |
| [Calls #747](https://gitlab.gnome.org/GNOME/calls/-/work_items/747) | July 2026 design issue; no linked implementation MR in the inspected metadata. | Use its interaction design when testing future upstream subscription support. |
| [Calls !505](https://gitlab.gnome.org/GNOME/calls/-/merge_requests/505) | Older draft work to store and reuse call-origin identities; source branch `store-origin-ids` in `devrtz/calls`. | Relevant history/re-dial design precedent, dating from 2022. It is not a current integrated multi-SIM stack. |
| [libqmi !434](https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/merge_requests/434) | WDS/QoS subscription and mux binding, merged October 2025. | Already-landed IMS/data-session plumbing; not a complete multi-SIM modem implementation. |
| [libqmi !459](https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/merge_requests/459) | IMSA Get Bind, merged May 2026. | Diagnostic support for reading subscription binding; not evidence of dual standby. |

The Settings merge corrects a gap in the initial survey for #58: enumerating one
WWAN page per modem does not imply the page has no physical-slot selector. Both
the modem list and controls inside each modem page need inspection.

The [50.0 device-page source](https://gitlab.gnome.org/GNOME/gnome-control-center/-/blob/50.0/panels/wwan/cc-wwan-device-page.c)
contains the slot-selection row; the backend uses MM's `SimSlots` and
`SetPrimarySimSlot`, including handling the modem's disappearance/reappearance.
The MR's nine-commit series ends at
`9627d5b3dc4b54d3f89ab40b3dd6a540bea043b0`.
This is release code to inspect, not a new branch requiring a wholesale stack
upgrade. Its actual presentation and switching behaviour in PocketFed still
need a coordinated check.

The old Calls branch is directly obtainable as
[`devrtz/calls:store-origin-ids`](https://gitlab.gnome.org/devrtz/calls/-/tree/store-origin-ids),
tip `71b6c6f933e8d3b950467c2bf505f75af0771112` (19 April 2022).
It uses modem IMEI as an origin identity, which cannot distinguish two
subscriptions on the same modem, changes the Calls database schema and mentions
GOM patch dependencies. Treat it as design/source history rather than a
drop-in trial of the present grant effort.

## Public WIP search, 14 September 2026

No identifiable current Guido/NLnet DSDS implementation branch was found in the
following bounded public search:

- All 31 advertised heads in
  [Guido's MM fork](https://gitlab.freedesktop.org/agx/ModemManager/-/branches)
  and all 19 in his
  [libqmi fork](https://gitlab.freedesktop.org/agx/libqmi/-/branches), plus his
  upstream MRs. The recent changes found concern cell broadcast or maintenance.
- Upstream MM/libqmi branch inventories and relevant SIM/subscription MRs;
  public MM forks belonging to `dahopem`, `devrtz`, `lynxis` and `dos`.
- Paginated branch inventories for `guidog/calls`, `guidog/phosh`,
  `devrtz/calls`, `devrtz/phosh`, upstream Calls and Phosh; relevant searches in
  Guido's `gnome-control-center2` fork. Current Calls open MRs did not expose a
  multi-SIM implementation, and #747 had zero notes and no linked MR.
- Full Phosh monthly development reports from January through August 2026.
  None identified a multi-SIM implementation branch; the association's separate
  July article provides the positive design-work evidence above.

Public visibility has limits: some FDO issue-note endpoints returned 401 and
Guido's alternate cgit index returned 503. This is not evidence that no work is
in progress, nor an audit of private grant deliverables. The original MM
[`dual-sim` MR !330](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/merge_requests/330)
is from 2020 and explicitly implemented single standby; it is not the 2026
initiative's missing branch.

The existing ModemManager discussions remain useful coordination points:

- [#761](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/issues/761):
  dual-SIM support for QMI modems and primary/secondary provisioning.
- [#649](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/issues/649):
  integrating Qualcomm UIM slot/application configuration into the backend.
- [#1083](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/issues/1083):
  which layer should own automatic slot-selection policy.

An existing QMI slot switch, two SIM objects or multiple bearer interfaces does
not establish simultaneous reachability. Future trials must retain subscription
identity through registration, calls, SMS, data and IMS, and distinguish current
firmware configuration from maximum hardware capability.

## Coordination before implementation

The first useful upstream questions are:

1. Which public branches or pending series should downstream testers build?
2. Which modem hardware and firmware combinations are currently targeted?
3. Is a subscription API already agreed, and which components are ready for
   independent testing?
4. Would a Sargo physical-SIM/eSIM test case, reproducible QMI observations or
   Fedora packaging help the current milestones?

PocketFed can contribute device characterization, isolated package trials,
per-carrier connection-profile validation and lifecycle acceptance while using
the upstream design. Coordinate ownership before developing a parallel selector
or public subscription API. Do not treat absence of a discoverable public branch
as proof that no implementation exists.

No upstream issue/comment/contact message, device mutation or hardware trial is
part of this research. Device-specific evidence remains in #58; raw diagnostics
and personal handset metadata are excluded from this documentation change.
