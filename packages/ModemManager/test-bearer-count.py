#!/usr/bin/env python3
"""Compile and exercise the bearer counter from the prepared source tree.

The production enums, CountBearersContext, bearer_count(), and
mm_iface_modem_count_bearers() are extracted without changing their C code.
Only the surrounding modem/bearer objects are replaced with small fixtures;
the counting and capacity calculation are never reimplemented in the test.
"""

import os
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys
import tempfile


def enum_from(path, name):
    source = path.read_text()
    match = re.search(r"typedef enum[^{}]*\{[^}]*\}\s*" + name + r"\s*;", source)
    if not match:
        raise RuntimeError(f"Cannot find production enum {name} in {path}")
    return match.group()


def counter_from(path):
    source = path.read_text()
    context_end = source.index("} CountBearersContext;")
    start = source.rfind("typedef struct {", 0, context_end)
    function = source.index("\nmm_iface_modem_count_bearers (", context_end)
    end = source.index("\n/*****************************************************************************/", function)
    if start < 0 or "\nbearer_count (" not in source[start:end]:
        raise RuntimeError("Cannot locate the production bearer counter")
    return source[start:end]


FIXTURES = r"""
typedef struct {
    MMBearerStatus status;
    gboolean multiplexed;
} MMBaseBearer;
typedef struct {
    MMBaseBearer *bearers;
    guint length;
    guint max_active;
    guint max_multiplexed;
} MMBearerList;
typedef struct { MMBearerList *list; } MMIfaceModem;
typedef void (*MMBearerListForeachFunc) (MMBaseBearer *, gpointer);

static void release_fixture (MMBearerList *list) { (void) list; }
G_DEFINE_AUTOPTR_CLEANUP_FUNC (MMBearerList, release_fixture)

#define MM_BASE_BEARER(bearer) (bearer)
#define MM_GDBUS_BEARER(bearer) (bearer)
#define MM_IFACE_MODEM_BEARER_LIST "bearer-list"
#define MM_CORE_ERROR (g_quark_from_static_string ("test-modem-error"))
#define MM_CORE_ERROR_FAILED 1
#define g_object_get(self, key, result, end) (*(result) = (self)->list)

static MMBearerStatus mm_base_bearer_get_status (MMBaseBearer *b)
{ return b->status; }
static gboolean mm_gdbus_bearer_get_multiplexed (MMBaseBearer *b)
{ return b->multiplexed; }
static guint mm_bearer_list_get_max_active (MMBearerList *list)
{ return list->max_active; }
static guint mm_bearer_list_get_max_active_multiplexed (MMBearerList *list)
{ return list->max_multiplexed; }
static void mm_bearer_list_foreach (MMBearerList *list,
                                   MMBearerListForeachFunc callback,
                                   gpointer context)
{
    for (guint i = 0; i < list->length; i++)
        callback (&list->bearers[i], context);
}
"""

TESTS = r"""
typedef struct {
    const gchar *name;
    guint regular_capacity, multiplexed_capacity;
    MMIfaceModemCountBearersFlags flags;
    guint expected_count, expected_capacity;
    MMBaseBearer bearers[4];
    guint length;
} TestCase;

static const TestCase cases[] = {
    /* The values recovered from the Sargo suspend core: one multiplexed
     * connection, no regular capacity, and 254 multiplexed slots. */
    { "/bearer-count/sargo-suspend", 0, 254,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE, 1, 254,
      {{MM_BEARER_STATUS_CONNECTED, TRUE}}, 1 },
    { "/bearer-count/sargo-connected", 0, 254,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_CONNECTED, 1, 254,
      {{MM_BEARER_STATUS_CONNECTED, TRUE}}, 1 },
    { "/bearer-count/multiple-multiplexed", 1, 4,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE, 2, 5,
      {{MM_BEARER_STATUS_CONNECTED, TRUE},
       {MM_BEARER_STATUS_CONNECTED, TRUE}}, 2 },
    { "/bearer-count/mixed", 1, 4,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_CONNECTED, 2, 5,
      {{MM_BEARER_STATUS_CONNECTED, FALSE},
       {MM_BEARER_STATUS_CONNECTED, TRUE}}, 2 },
    { "/bearer-count/multiplexed-filter", 1, 4,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_MULTIPLEXED, 1, 4,
      {{MM_BEARER_STATUS_CONNECTED, FALSE},
       {MM_BEARER_STATUS_CONNECTED, TRUE}}, 2 },
    { "/bearer-count/active-transitions", 0, 254,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE, 2, 254,
      {{MM_BEARER_STATUS_DISCONNECTED, FALSE},
       {MM_BEARER_STATUS_DISCONNECTING, FALSE},
       {MM_BEARER_STATUS_CONNECTING, FALSE},
       {MM_BEARER_STATUS_CONNECTED, TRUE}}, 4 },
    { "/bearer-count/connected-transitions", 0, 254,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_CONNECTED, 1, 254,
      {{MM_BEARER_STATUS_CONNECTING, FALSE},
       {MM_BEARER_STATUS_CONNECTED, TRUE}}, 2 },
    { "/bearer-count/ordinary-modem", 1, 0,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE, 1, 1,
      {{MM_BEARER_STATUS_CONNECTED, FALSE}}, 1 },
    { "/bearer-count/empty-list", 0, 254,
      MM_IFACE_MODEM_COUNT_BEARERS_FLAG_ACTIVE, 0, 254,
      {{0}}, 0 },
};

static void check_case (gconstpointer data)
{
    const TestCase *test = data;
    MMBearerList list = { (MMBaseBearer *) test->bearers, test->length,
                         test->regular_capacity, test->multiplexed_capacity };
    MMIfaceModem modem = { &list };
    g_autoptr(GError) error = NULL;
    guint current = G_MAXUINT, maximum = G_MAXUINT;

    g_assert_true (mm_iface_modem_count_bearers (&modem, test->flags,
                                                &current, &maximum, &error));
    g_assert_no_error (error);
    g_assert_cmpuint (current, ==, test->expected_count);
    g_assert_cmpuint (maximum, ==, test->expected_capacity);
}

int main (int argc, char **argv)
{
    g_test_init (&argc, &argv, NULL);
    for (guint i = 0; i < G_N_ELEMENTS (cases); i++)
        g_test_add_data_func (cases[i].name, &cases[i], check_case);
    return g_test_run ();
}
"""


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} PREPARED_MODEMMANAGER_SOURCE")
    source = Path(sys.argv[1]) / "src"
    program = "\n".join([
        "#include <glib.h>",
        enum_from(source / "mm-base-bearer.h", "MMBearerStatus"),
        enum_from(source / "mm-iface-modem.h", "MMIfaceModemCountBearersFlags"),
        FIXTURES,
        counter_from(source / "mm-iface-modem.c"),
        TESTS,
    ])
    # The unpatched negative control intentionally aborts; keep it from
    # creating unrelated crash artifacts on developer machines/builders.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "glib-2.0"], text=True))
    with tempfile.TemporaryDirectory(prefix="mm-bearer-count-") as temp:
        c_file = Path(temp) / "test.c"
        executable = Path(temp) / "test-bearer-count"
        c_file.write_text(program)
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) + [
            "-std=gnu11", "-Wall", "-Wextra", "-Werror", str(c_file),
            "-o", str(executable), *flags,
        ], check=True)
        result = subprocess.run([str(executable)])
        return 0 if result.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
