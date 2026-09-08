/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Click a point on a disposable headless Wayland output. */
#include <assert.h>
#include <linux/input-event-codes.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "virtual-pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *manager;
static struct wl_seat *seat;

static void
global (void *data, struct wl_registry *registry, uint32_t name,
        const char *interface, uint32_t version)
{
  if (!strcmp (interface, "zwlr_virtual_pointer_manager_v1"))
    manager = wl_registry_bind (registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
  else if (!strcmp (interface, "wl_seat"))
    seat = wl_registry_bind (registry, name, &wl_seat_interface, 1);
}

static void removed (void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener listener = {global, removed};

static uint32_t
milliseconds (void)
{
  struct timespec now;
  clock_gettime (CLOCK_MONOTONIC, &now);
  return (uint32_t) ((uint64_t) now.tv_sec * 1000 + now.tv_nsec / 1000000);
}

int
main (int argc, char **argv)
{
  struct wl_display *display;
  struct wl_registry *registry;
  struct zwlr_virtual_pointer_v1 *pointer;

  assert (argc == 5);
  display = wl_display_connect (NULL);
  assert (display);
  registry = wl_display_get_registry (display);
  wl_registry_add_listener (registry, &listener, NULL);
  assert (wl_display_roundtrip (display) >= 0);
  assert (manager && seat);
  pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer (manager, seat);
  assert (wl_display_roundtrip (display) >= 0);
  /* Creating this device adds pointer capability. Let other clients bind it
   * before sending the first press, otherwise only release can reach GTK. */
  usleep (150000);
  zwlr_virtual_pointer_v1_motion_absolute (pointer, milliseconds (), atoi (argv[3]), atoi (argv[4]),
                                          atoi (argv[1]), atoi (argv[2]));
  zwlr_virtual_pointer_v1_frame (pointer);
  assert (wl_display_roundtrip (display) >= 0);
  usleep (50000);
  zwlr_virtual_pointer_v1_button (pointer, milliseconds (), BTN_LEFT, WL_POINTER_BUTTON_STATE_PRESSED);
  zwlr_virtual_pointer_v1_frame (pointer);
  assert (wl_display_roundtrip (display) >= 0);
  usleep (25000);
  zwlr_virtual_pointer_v1_button (pointer, milliseconds (), BTN_LEFT, WL_POINTER_BUTTON_STATE_RELEASED);
  zwlr_virtual_pointer_v1_frame (pointer);
  assert (wl_display_roundtrip (display) >= 0);
  zwlr_virtual_pointer_v1_destroy (pointer);
  zwlr_virtual_pointer_manager_v1_destroy (manager);
  wl_display_flush (display);
  wl_display_disconnect (display);
  return 0;
}
