/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <gio/gio.h>

G_BEGIN_DECLS
#define PHOSH_TYPE_FINGERPRINT_AUTH (phosh_fingerprint_auth_get_type ())
G_DECLARE_FINAL_TYPE (PhoshFingerprintAuth, phosh_fingerprint_auth, PHOSH, FINGERPRINT_AUTH, GObject)

PhoshFingerprintAuth *phosh_fingerprint_auth_new (void);
void phosh_fingerprint_auth_start (PhoshFingerprintAuth *self,
                                  GAsyncReadyCallback callback,
                                  gpointer user_data);
void phosh_fingerprint_auth_cancel (PhoshFingerprintAuth *self);
gboolean phosh_fingerprint_auth_finish (PhoshFingerprintAuth *self,
                                       GAsyncResult *result,
                                       GError **error);
G_END_DECLS
