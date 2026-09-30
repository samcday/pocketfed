#!/usr/bin/env python3
"""Generate the integration patch from the verified Phosh 0.57.0 archive.

This does not modify a checkout or installed Phosh. The helper/PAM service are
packaged separately. The existing rejected-PIN patch remains independently
applicable because this change does not alter auth.c.
"""
import difflib
import hashlib
from pathlib import Path
import sys
import tarfile

base = Path(__file__).resolve().parent
archive = Path(sys.argv[1])
if hashlib.sha256(archive.read_bytes()).hexdigest() != "25e9332da735a3e0c0fe05673d5ce62e35b87780a3e5fa770075bed6bd4d0b1b":
    raise SystemExit("Expected the recorded Phosh 0.57.0 source archive")
with tarfile.open(archive) as tar:
    old = {name: tar.extractfile("phosh-v0.57.0/" + name).read().decode()
           for name in ("src/lockscreen.c", "src/meson.build")}
new = dict(old)

def replace(name, before, after):
    if new[name].count(before) != 1:
        raise SystemExit(f"Non-unique patch anchor in {name}: {before[:60]!r}")
    new[name] = new[name].replace(before, after)

replace("src/lockscreen.c", '#include "auth.h"', '#include "auth.h"\n#include "fingerprint-auth.h"')
replace("src/lockscreen.c", "  PhoshAuth          *auth;", "  PhoshAuth          *auth;\n  PhoshFingerprintAuth *fingerprint;\n  gboolean             fingerprint_blanked;")
anchor = "G_DEFINE_TYPE_WITH_PRIVATE (PhoshLockscreen, phosh_lockscreen, PHOSH_TYPE_LAYER_SURFACE)"
code = r'''

static void
stop_fingerprint (PhoshLockscreen *self)
{
  PhoshLockscreenPrivate *priv = phosh_lockscreen_get_instance_private (self);
  if (priv->fingerprint)
    phosh_fingerprint_auth_cancel (priv->fingerprint);
  g_clear_object (&priv->fingerprint);
}

static void
on_fingerprint_message (PhoshLockscreen *self, const char *message, PhoshFingerprintAuth *auth)
{
  PhoshLockscreenPrivate *priv = phosh_lockscreen_get_instance_private (self);
  if (priv->fingerprint == auth && !priv->auth)
    phosh_lockscreen_set_unlock_status (self, message);
}

static void
on_fingerprint_done (GObject *source, GAsyncResult *result, gpointer user_data)
{
  GWeakRef *weak = user_data;
  g_autoptr (PhoshLockscreen) self = g_weak_ref_get (weak);
  g_autoptr (GError) error = NULL;
  PhoshFingerprintAuth *auth = PHOSH_FINGERPRINT_AUTH (source);
  PhoshLockscreenPrivate *priv;
  gboolean success = phosh_fingerprint_auth_finish (auth, result, &error);

  g_weak_ref_clear (weak);
  g_free (weak);
  if (!self)
    return;
  priv = phosh_lockscreen_get_instance_private (self);
  /* A cancelled/replaced transaction can never unlock a later screen. */
  if (priv->fingerprint != auth)
    return;
  g_clear_object (&priv->fingerprint);
  if (success && priv->require_unlock && !priv->auth &&
      gtk_widget_get_mapped (GTK_WIDGET (self)) &&
      gtk_widget_is_sensitive (GTK_WIDGET (self)) &&
      !phosh_shell_get_blanked (phosh_shell_get_default ()) &&
      gtk_entry_get_text_length (GTK_ENTRY (priv->entry_pin)) == 0)
    g_signal_emit (self, signals[LOCKSCREEN_UNLOCK], 0);
  else if (!priv->auth)
    phosh_lockscreen_set_unlock_status (self, _("Enter Passcode"));
}

static void
start_fingerprint (PhoshLockscreen *self)
{
  PhoshLockscreenPrivate *priv = phosh_lockscreen_get_instance_private (self);
  GWeakRef *weak;

  /* Greeter subclasses own a selected-user greetd transaction. Do not run
   * the greeter process owner's fingerprint service from the base widget. */
  if (G_OBJECT_TYPE (self) != PHOSH_TYPE_LOCKSCREEN || !priv->require_unlock ||
      priv->fingerprint || priv->auth ||
      !gtk_widget_get_mapped (GTK_WIDGET (self)) ||
      !gtk_widget_is_sensitive (GTK_WIDGET (self)) ||
      phosh_shell_get_blanked (phosh_shell_get_default ()) ||
      gtk_entry_get_text_length (GTK_ENTRY (priv->entry_pin)) != 0)
    return;
  weak = g_new0 (GWeakRef, 1);
  g_weak_ref_init (weak, self);
  priv->fingerprint = phosh_fingerprint_auth_new ();
  g_signal_connect_object (priv->fingerprint, "message", G_CALLBACK (on_fingerprint_message),
                           self, G_CONNECT_SWAPPED);
  phosh_fingerprint_auth_start (priv->fingerprint, on_fingerprint_done, weak);
}

static void
on_fingerprint_screen_state (PhoshLockscreen *self, GParamSpec *pspec, PhoshShell *shell)
{
  PhoshLockscreenPrivate *priv = phosh_lockscreen_get_instance_private (self);
  gboolean blanked = phosh_shell_get_blanked (shell);

  if (priv->fingerprint_blanked == blanked)
    return;
  priv->fingerprint_blanked = blanked;
  if (blanked)
    stop_fingerprint (self);
  else
    start_fingerprint (self);
}

static void
on_fingerprint_gate_changed (PhoshLockscreen *self, GParamSpec *pspec, GObject *object)
{
  PhoshLockscreenPrivate *priv = phosh_lockscreen_get_instance_private (self);
  if (!priv->require_unlock || !gtk_widget_is_sensitive (GTK_WIDGET (self)))
    stop_fingerprint (self);
  else
    start_fingerprint (self);
}
'''
replace("src/lockscreen.c", anchor, anchor + code)
replace("src/lockscreen.c", "                                         PHOSH_LAYER_SURFACE (self));\n}", "                                         PHOSH_LAYER_SURFACE (self));\n  start_fingerprint (self);\n}")
replace("src/lockscreen.c", "  gtk_widget_set_sensitive (priv->btn_submit, length != 0);", "  gtk_widget_set_sensitive (priv->btn_submit, length != 0);\n  if (length)\n    stop_fingerprint (self);\n  else\n    start_fingerprint (self);")
replace("src/lockscreen.c", "  shell = phosh_shell_get_default ();\n  osk_manager", "  shell = phosh_shell_get_default ();\n  priv->fingerprint_blanked = phosh_shell_get_blanked (shell);\n  g_signal_connect_object (shell, \"notify::shell-state\",\n                           G_CALLBACK (on_fingerprint_screen_state), self, G_CONNECT_SWAPPED);\n  g_signal_connect_object (self, \"notify::sensitive\",\n                           G_CALLBACK (on_fingerprint_gate_changed), self, G_CONNECT_SWAPPED);\n  g_signal_connect_object (self, \"notify::require-unlock\",\n                           G_CALLBACK (on_fingerprint_gate_changed), self, G_CONNECT_SWAPPED);\n  g_signal_connect_object (self, \"notify::page\",\n                           G_CALLBACK (on_fingerprint_gate_changed), self, G_CONNECT_SWAPPED);\n  g_signal_connect_swapped (self, \"destroy\", G_CALLBACK (stop_fingerprint), self);\n  g_signal_connect_swapped (self, \"unmap\", G_CALLBACK (stop_fingerprint), self);\n  osk_manager")
replace("src/lockscreen.c", "  g_clear_object (&priv->notification_settings);", "  stop_fingerprint (self);\n  g_clear_object (&priv->notification_settings);")
replace("src/lockscreen.c", "  input = gtk_entry_get_text (GTK_ENTRY (priv->entry_pin));", "  stop_fingerprint (self);\n  input = gtk_entry_get_text (GTK_ENTRY (priv->entry_pin));")
replace("src/meson.build", "  'auth.h',", "  'auth.h',\n  'fingerprint-auth.h',")
replace("src/meson.build", "  'auth.c',", "  'auth.c',\n  'fingerprint-auth.c',")
for name in ("fingerprint-auth.c", "fingerprint-auth.h"):
    new["src/" + name] = (base / name).read_text()

header = """Subject: [PATCH] lockscreen: run fingerprint PAM independently of PIN entry

Use a separate fingerprint socket client so a scan can be cancelled when
the user types a PIN, the display blanks, or the lockscreen is destroyed.
Only successful authentication plus account management may unlock. Discard
cancelled/stale completions and exclude greeter subclasses.

Requires the separately packaged phosh-fingerprint-auth client, peer-UID-bound
PAM worker, and enabled socket. Device acceptance remains required before
promotion; package and synthetic test results are recorded separately.

"""
diff = header
for name in sorted(new):
    diff += "".join(difflib.unified_diff(old.get(name, "").splitlines(keepends=True),
                                        new[name].splitlines(keepends=True),
                                        fromfile="a/" + name if name in old else "/dev/null",
                                        tofile="b/" + name))
(base / "0001-lockscreen-add-cancellable-fingerprint-auth.patch").write_text(diff)
print("Generated source patch; no checkout or installed authentication changed")
