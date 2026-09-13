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
the project's agreement; the public award page is not a progress dashboard.
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
The issue and the association article strongly suggest a shared design effort;
the public material does not establish whether this issue is a particular
contractual grant deliverable.

## Reusable code and design

| Item | State at inspection | Relevance |
| --- | --- | --- |
| [GNOME Settings !2867](https://gitlab.gnome.org/GNOME/gnome-control-center/-/merge_requests/2867) | Primary-SIM-slot selector merged 9 February 2026; proposal began October 2024. | Audit the existing selector before writing a new one. Selecting one active slot is distinct from simultaneous standby and independent voice/SMS/data defaults. |
| [Calls #747](https://gitlab.gnome.org/GNOME/calls/-/work_items/747) | July 2026 design issue; no linked implementation MR in the inspected metadata. | Use its interaction design when testing future upstream subscription support. |
| [Calls !505](https://gitlab.gnome.org/GNOME/calls/-/merge_requests/505) | Older draft work to store and reuse call-origin identities; source branch `store-origin-ids` in `devrtz/calls`. | Relevant history/re-dial design precedent, dating from 2022. It is not a current integrated multi-SIM stack. |

The Settings merge corrects a gap in the initial survey for #58: enumerating one
WWAN page per modem does not imply the page has no physical-slot selector. Both
the modem list and controls inside each modem page need inspection.

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
