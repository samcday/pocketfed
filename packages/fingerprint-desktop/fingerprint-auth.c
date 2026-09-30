/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "fingerprint-auth.h"

#ifndef FINGERPRINT_HELPER_PATH
#define FINGERPRINT_HELPER_PATH "/usr/libexec/phosh-fingerprint-auth"
#endif

struct _PhoshFingerprintAuth {
  GObject parent;
  GSubprocess *child;
  GDataInputStream *messages;
  gboolean started;
  gboolean cancelled;
};
G_DEFINE_TYPE (PhoshFingerprintAuth, phosh_fingerprint_auth, G_TYPE_OBJECT)

static guint message_signal;

static void
on_message (GObject *source, GAsyncResult *result, gpointer user_data)
{
  g_autoptr (PhoshFingerprintAuth) self = PHOSH_FINGERPRINT_AUTH (user_data);
  g_autofree char *line = g_data_input_stream_read_line_finish (G_DATA_INPUT_STREAM (source),
                                                              result, NULL, NULL);
  if (!line || self->cancelled)
    return;
  if (g_utf8_validate (line, -1, NULL))
    g_signal_emit (self, message_signal, 0, line);
  if (!self->cancelled)
    g_data_input_stream_read_line_async (self->messages, G_PRIORITY_DEFAULT,
                                         NULL, on_message, g_object_ref (self));
}

static void
on_child_done (GObject *source, GAsyncResult *result, gpointer user_data)
{
  g_autoptr (GTask) task = G_TASK (user_data);
  PhoshFingerprintAuth *self = g_task_get_source_object (task);
  g_autoptr (GError) error = NULL;
  gboolean success = g_subprocess_wait_check_finish (G_SUBPROCESS (source), result, &error);

  g_clear_object (&self->child);
  /* Cancellation wins even if a successful child exit raced with it. */
  if (self->cancelled)
    g_task_return_new_error (task, G_IO_ERROR, G_IO_ERROR_CANCELLED, "Fingerprint cancelled");
  else if (!success)
    g_task_return_error (task, g_steal_pointer (&error));
  else
    g_task_return_boolean (task, TRUE);
}

void
phosh_fingerprint_auth_cancel (PhoshFingerprintAuth *self)
{
  g_return_if_fail (PHOSH_IS_FINGERPRINT_AUTH (self));
  self->cancelled = TRUE;
  if (self->child)
    g_subprocess_force_exit (self->child);
}

void
phosh_fingerprint_auth_start (PhoshFingerprintAuth *self,
                              GAsyncReadyCallback callback,
                              gpointer user_data)
{
  g_autoptr (GError) error = NULL;
  GTask *task;
  g_return_if_fail (PHOSH_IS_FINGERPRINT_AUTH (self));
  g_return_if_fail (!self->started);
  self->started = TRUE;
  task = g_task_new (self, NULL, callback, user_data);
  if (self->cancelled) {
    g_task_return_new_error (task, G_IO_ERROR, G_IO_ERROR_CANCELLED, "Fingerprint cancelled");
    g_object_unref (task);
    return;
  }
  self->child = g_subprocess_new (G_SUBPROCESS_FLAGS_STDIN_PIPE |
                                 G_SUBPROCESS_FLAGS_STDOUT_PIPE |
                                 G_SUBPROCESS_FLAGS_STDERR_SILENCE,
                                 &error, FINGERPRINT_HELPER_PATH, NULL);
  if (!self->child) {
    g_task_return_error (task, g_steal_pointer (&error));
    g_object_unref (task);
    return;
  }
  /* No credential can be read from the invoking terminal. */
  g_output_stream_close (g_subprocess_get_stdin_pipe (self->child), NULL, NULL);
  self->messages = g_data_input_stream_new (g_subprocess_get_stdout_pipe (self->child));
  g_data_input_stream_read_line_async (self->messages, G_PRIORITY_DEFAULT,
                                       NULL, on_message, g_object_ref (self));
  /* Always reap, including after cancel(). Do not cancel this wait operation. */
  g_subprocess_wait_check_async (self->child, NULL, on_child_done, task);
}

gboolean
phosh_fingerprint_auth_finish (PhoshFingerprintAuth *self,
                               GAsyncResult *result,
                               GError **error)
{
  g_return_val_if_fail (g_task_is_valid (result, self), FALSE);
  return g_task_propagate_boolean (G_TASK (result), error);
}

static void
phosh_fingerprint_auth_finalize (GObject *object)
{
  PhoshFingerprintAuth *self = PHOSH_FINGERPRINT_AUTH (object);
  g_clear_object (&self->child);
  g_clear_object (&self->messages);
  G_OBJECT_CLASS (phosh_fingerprint_auth_parent_class)->finalize (object);
}

static void
phosh_fingerprint_auth_class_init (PhoshFingerprintAuthClass *klass)
{
  G_OBJECT_CLASS (klass)->finalize = phosh_fingerprint_auth_finalize;
  message_signal = g_signal_new ("message", G_TYPE_FROM_CLASS (klass), G_SIGNAL_RUN_LAST,
                                  0, NULL, NULL, NULL, G_TYPE_NONE, 1, G_TYPE_STRING);
}

static void
phosh_fingerprint_auth_init (PhoshFingerprintAuth *self)
{
  (void) self;
}

PhoshFingerprintAuth *
phosh_fingerprint_auth_new (void)
{
  return g_object_new (PHOSH_TYPE_FINGERPRINT_AUTH, NULL);
}
