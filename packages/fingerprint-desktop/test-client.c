/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "fingerprint-auth.h"

typedef struct {
  GMainLoop *loop;
  gboolean success;
  GError *error;
} Result;

static void done (GObject *source, GAsyncResult *result, gpointer user_data)
{
  Result *r = user_data;
  r->success = phosh_fingerprint_auth_finish (PHOSH_FINGERPRINT_AUTH (source), result, &r->error);
  g_main_loop_quit (r->loop);
}

static void check (const char *mode, gboolean cancel, gboolean cancel_before, gboolean expect_success)
{
  g_autoptr (PhoshFingerprintAuth) auth = phosh_fingerprint_auth_new ();
  Result r = { .loop = g_main_loop_new (NULL, FALSE) };
  g_setenv ("FINGERPRINT_FAKE_MODE", mode, TRUE);
  if (cancel_before)
    phosh_fingerprint_auth_cancel (auth);
  phosh_fingerprint_auth_start (auth, done, &r);
  if (cancel)
    phosh_fingerprint_auth_cancel (auth);
  g_main_loop_run (r.loop);
  g_assert_cmpint (r.success, ==, expect_success);
  if (cancel || cancel_before)
    g_assert_error (r.error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
  else if (!expect_success)
    g_assert_nonnull (r.error);
  else
    g_assert_no_error (r.error);
  g_clear_error (&r.error);
  g_main_loop_unref (r.loop);
}

int main (void)
{
  check ("success", FALSE, FALSE, TRUE);
  check ("reject", FALSE, FALSE, FALSE);
  check ("signal", FALSE, FALSE, FALSE);
  check ("block", TRUE, FALSE, FALSE);
  check ("success", TRUE, FALSE, FALSE);
  check ("success", FALSE, TRUE, FALSE);
  g_print ("client: successful exit, rejection, signal, cancellation, raced success and pre-cancel passed\n");
  return 0;
}
