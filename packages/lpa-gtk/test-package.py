#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise staged RPM resources and UI; forbid use of the real lpac backend."""

import ast
import gettext
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

assert os.environ.get("LPA_GTK_BACKEND") == "dummy"
root = Path(sys.argv[1])
site = sys.argv[2]
launcher = (root / "usr/bin/lpa-gtk").read_text()
paths = {
    node.targets[0].id: ast.literal_eval(node.value)
    for node in ast.parse(launcher).body
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    and node.targets[0].id in {"pythondir", "pkgdatadir"}
}
# Meson's get_install_dir() may include a trailing slash; compare paths,
# while still rejecting a launcher wired to the wrong installed location.
assert Path(paths["pythondir"]) == Path(site), paths
assert Path(paths["pkgdatadir"]) == Path("/usr/share/lpa-gtk"), paths
print(f"PASS: launcher paths {paths}")
sys.path.insert(0, str(root / site.lstrip("/")))
gettext.install("lpa-gtk")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GLib

resource = Gio.Resource.load(str(root / "usr/share/lpa-gtk/lpa-gtk.gresource"))
resource._register()
from lpa_gtk import config, esim, main

assert config.APP_VERSION == "0.4"
assert config.APP_ID == "eu.lucaweiss.lpa_gtk"
app = main.Application()
passed = False
errors = []


def exception_hook(kind, value, tb):
    errors.append(str(value))
    traceback.print_exception(kind, value, tb)
    app.quit()


sys.excepthook = exception_hook


def check_window():
    global passed
    try:
        win = app.get_active_window()
        assert win is not None and win.get_visible()
        assert win.active_slot == 1
        assert all(isinstance(b, esim.DummyBackend)
                   for b in win.esim_manager._backends.values())
        assert win.list_page.profile_list_box.get_first_child() is not None
        win.profile_add_button.emit("clicked")
        assert win.nav_view.get_visible_page() == win.nav_download
        win.download_page.entry_code.set_text("LPA:1$example.invalid$dummy")
        win.download_page.reset()
        assert win.download_page.entry_code.get_text() == ""
        win.nav_view.pop()
        win.sim_slot_group.set_active_name("2")
        assert win.active_slot == 2
        assert win.esim_manager.get_profiles(2)
        passed = True
        print("PASS: staged resources, main window, profile list, add page, slot selector")
    except BaseException:
        exception_hook(*sys.exc_info())
    finally:
        app.quit()
    return GLib.SOURCE_REMOVE


def timed_out():
    errors.append("UI smoke test timed out")
    app.quit()
    return GLib.SOURCE_REMOVE


GLib.idle_add(check_window)
GLib.timeout_add_seconds(15, timed_out)
with patch.object(esim.LpacBackend, "__init__",
                  side_effect=AssertionError("Real lpac backend is forbidden in RPM tests")):
    result = app.run(["lpa-gtk-package-test"])
assert result == 0 and passed and not errors, (result, passed, errors)
