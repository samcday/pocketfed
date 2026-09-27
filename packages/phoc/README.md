# Phoc

Fedora Rawhide's phoc packaging, plus a fix for a touch-up use-after-free
([upstream issue #408](https://gitlab.gnome.org/World/Phosh/phoc/-/issues/408)).
When a fling closes Phosh's top panel, the touch-end gesture cancels the touch.
wlroots frees the seat's touch point, and `phoc_cursor_handle_touch_up` then
reads a stale pointer it fetched before gesture dispatch. Phoc segfaults and
the session drops to the greeter. The patch looks the point up after gesture
dispatch and adds a `tests/test-cursor.c` regression test. Upstream fixed the
same bug in `a9e2c3db` (MR !812), first released in 0.58~alpha1, which uses
text-input events that Fedora's system wlroots 0.20.2 lacks.

The packaging is Fedora dist-git
[`5cc17f1c`](https://src.fedoraproject.org/rpms/phoc/c/5cc17f1c3a62dbbe55323152d6865d08799a9e71)
(koji `phoc-0.57.0-2.fc46`). The spec adds the patch, sets release
`2.1.pocketfed`, provides `phoc-touch-up-lifetime-fix`, and expands
`%autochangelog`. Build it for `fedora-rawhide-aarch64` and
`fedora-rawhide-x86_64`.

The Phosh image pins this build from the `samcday/pocketfed` COPR at
`priority=50`, which shadows Fedora phoc whatever its NVR. As soon as Rawhide
ships phoc >= 0.57.0-3 with the fix, or 0.58, retire this fork. To retire it:
- delete this directory;
- remove `phoc` from the `includepkgs` lists in the phosh and device repos;
- remove the pin from `phosh/Containerfile`;
- delete the COPR's phoc builds.
