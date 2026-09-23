# Mesa

Fedora Rawhide's mesa packaging, plus Mesa
[MR !44653](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/44653).
The MR emits `CP_EVENT_WRITE HLSQ_FLUSH` before indirect constant loads on
Adreno a3xx, which otherwise hang A306 (msm8916) boards
([issue #80](https://github.com/samcday/pocketfed/issues/80)). Only the
freedreno a3xx path changes.

The packaging is Fedora dist-git
[`941c0407`](https://src.fedoraproject.org/rpms/mesa/c/941c0407444419a38856a92013f701524836dff1)
(koji `mesa-26.2.3-1.fc46`). The patch is `git format-patch` of the MR's
commit `d39138dc`. The spec adds the patch, sets release `1.2.pocketfed`, and
replaces `%autochangelog` with the PocketFed entries followed by the changelog
rpmautospec generated for Fedora's build. Build with the common `make_srpm`
flow for `fedora-rawhide-aarch64` and `fedora-rawhide-x86_64`.

Base images install Mesa from the `samcday/pocketfed` COPR at `priority=50`,
so every image gets this build. Newer Fedora Mesa reaches images only after
this fork is rebased or retired. Retire it once Fedora ships a Mesa containing
the MR: delete this directory and the COPR's Mesa builds.
