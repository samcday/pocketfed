# Upstream follow-through

Public evidence for bugs investigated while using PocketFed. Each report keeps
the observed failure, proposed patch, reproduction instructions, source
provenance, validation results and remaining work together. These are candidate
fixes for upstream review; publishing them here does not claim upstream
acceptance or a fixed distribution release.

| Project | Failure | Evidence and proposal |
| --- | --- | --- |
| GTK4 | On-screen keyboard preedit disappears after caret geometry updates | [Report, bisect, patch and integration harness](gtk4/) |
| Flatpak | Chromium waits indefinitely after a nested sandbox loses its startup notification | [Report, commit boundary, patch and comparison tests](flatpak/) |
| WirePlumber | Role loopbacks can chain across roles after output removal and leave playback stalled | [Report, two-patch series and isolated reconnect reproducer](wireplumber/) |

GTK4 and Flatpak have identified introducing commits. WirePlumber is a confirmed
bug at the recorded revision; its first bad commit has not been established.
The individual tracking issues remain open through upstream review, a fixed
Fedora package, device verification, and retirement of any downstream workaround.

## Existing public work

The inventory also found work that already has a public record:

- [Phoc touch-up lifetime fix, PocketFed PR #30](https://github.com/samcday/pocketfed/pull/30).
- [Modem suspend cleanup and IMS recovery, PocketFed PR #29](https://github.com/samcday/pocketfed/pull/29).

These links preserve existing discussion rather than opening duplicate trackers.

## Contribution provenance and review

The investigations, candidate patches, reproducers and reports were developed
with AI assistance through Codex. Recorded program output, source inspection,
focused tests, and device-owner observations are distinguished in each report.
Test limits and existing suite failures are included. Upstream-derived code and
protocol files retain their existing notices; attribution and licensing of new
standalone harness code should be confirmed before incorporating it upstream.

Project policies checked on 8 September 2026:

- [GTK's contribution policy](https://gitlab.gnome.org/GNOME/gtk/-/blob/539d28f33b6d285a784c220e6c53ec499d75c078/CONTRIBUTING.md#ai-contribution-policy)
  permits AI-assisted contributions with disclosure, narrow scope, verification,
  understanding and human responsibility. It requires the human contributor to
  handle review feedback without sending that feedback to an LLM. GTK requests
  proposed code changes through merge requests.
- [Flatpak's contribution guide](https://github.com/flatpak/flatpak/blob/e382cbeb80ce9fbaab587a613a9f35ba0612d8cd/CONTRIBUTING.md)
  contains no adopted AI restriction. Its [open policy discussion](https://github.com/flatpak/flatpak/issues/6509)
  is not itself an adopted contribution ban.
- WirePlumber documents an AI-assistance attribution convention; both proposed
  patches retain their `Assisted-by` trailers. Its report links the checked
  upstream policy and ordinary merge-request workflow.

The public PocketFed issues are the follow-through queue. Upstream submission,
review decisions, release inclusion and downstream retirement should be linked
back there as they happen. Maintainer review and acceptance remain pending.
