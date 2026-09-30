/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* One connection, existing right-index enrollment, Claim then Release.
 * No verification, enrollment, deletion or credential operations.
 */
#include <gio/gio.h>
#include <stdio.h>
#include <string.h>

static GVariant *call(GDBusConnection *connection, const char *path,
                      const char *interface, const char *method,
                      GVariant *parameters, const GVariantType *reply_type,
                      GError **error)
{
    printf("FPC_CLAIM_ONLY %s.begin\n", method);
    GVariant *reply = g_dbus_connection_call_sync(connection,
        "net.reactivated.Fprint", path, interface, method, parameters,
        reply_type, G_DBUS_CALL_FLAGS_NONE, 45000, NULL, error);
    printf("FPC_CLAIM_ONLY %s.%s\n", method, reply ? "end" : "error");
    return reply;
}

int main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    g_autoptr(GError) error = NULL;
    g_autoptr(GVariant) device = NULL, listed = NULL, claim = NULL, release = NULL;
    g_auto(GStrv) labels = NULL;
    g_autoptr(GDBusConnection) bus = g_bus_get_sync(G_BUS_TYPE_SYSTEM, NULL, &error);
    if (!bus) goto fail;
    device = call(bus, "/net/reactivated/Fprint/Manager",
        "net.reactivated.Fprint.Manager", "GetDefaultDevice", NULL,
        G_VARIANT_TYPE("(o)"), &error);
    if (!device) goto fail;
    const char *path;
    g_variant_get(device, "(&o)", &path);
    if (strcmp(path, "/net/reactivated/Fprint/Device/0")) return 2;
    const char *interface = "net.reactivated.Fprint.Device";
    listed = call(bus, path, interface, "ListEnrolledFingers",
        g_variant_new("(s)", "sam"), G_VARIANT_TYPE("(as)"), &error);
    if (!listed) goto fail;
    g_variant_get(listed, "(^as)", &labels);
    gboolean enrolled = FALSE;
    for (unsigned i = 0; labels[i]; i++)
        enrolled |= !strcmp(labels[i], "right-index-finger");
    if (!enrolled) return 3;
    claim = call(bus, path, interface, "Claim",
        g_variant_new("(s)", "sam"), G_VARIANT_TYPE_UNIT, &error);
    if (!claim) goto fail;
    release = call(bus, path, interface, "Release", NULL,
        G_VARIANT_TYPE_UNIT, &error);
    if (!release) goto fail;
    puts("FPC_CLAIM_ONLY complete; capture_started=false");
    return 0;
fail:
    fprintf(stderr, "FPC_CLAIM_ONLY error: %s\n", error ? error->message : "unknown");
    return 1;
}
