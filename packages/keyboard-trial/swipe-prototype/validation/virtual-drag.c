/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Replay synthetic x/y/elapsed-ms samples on a disposable Wayland output. */
#include <assert.h>
#include <errno.h>
#include <linux/input-event-codes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include "virtual-pointer-client.h"

static struct zwlr_virtual_pointer_manager_v1 *manager;
static struct wl_seat *seat;

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version)
{
  if (!strcmp(interface, "zwlr_virtual_pointer_manager_v1"))
    manager = wl_registry_bind(registry, name, &zwlr_virtual_pointer_manager_v1_interface, 1);
  else if (!strcmp(interface, "wl_seat"))
    seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener listener = {global, removed};

static uint32_t milliseconds(void)
{
  struct timespec now;
  clock_gettime(CLOCK_MONOTONIC, &now);
  return (uint32_t)((uint64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000);
}

int main(int argc, char **argv)
{
  assert(argc == 4);
  unsigned width = strtoul(argv[1], NULL, 10), height = strtoul(argv[2], NULL, 10);
  assert(width && height);
  FILE *trace = fopen(argv[3], "r");
  assert(trace);
  struct wl_display *display = wl_display_connect(NULL);
  assert(display);
  struct wl_registry *registry = wl_display_get_registry(display);
  wl_registry_add_listener(registry, &listener, NULL);
  assert(wl_display_roundtrip(display) >= 0);
  assert(manager && seat);
  struct zwlr_virtual_pointer_v1 *pointer =
    zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager, seat);
  assert(wl_display_roundtrip(display) >= 0);
  usleep(150000);
  unsigned x, y, elapsed, previous = 0, count = 0;
  while (fscanf(trace, "%u %u %u", &x, &y, &elapsed) == 3) {
    assert(x <= width && y <= height && elapsed >= previous && elapsed <= 10000);
    if (elapsed > previous)
      usleep((elapsed - previous) * 1000);
    zwlr_virtual_pointer_v1_motion_absolute(pointer, milliseconds(), x, y, width, height);
    zwlr_virtual_pointer_v1_frame(pointer);
    assert(wl_display_roundtrip(display) >= 0);
    if (!count) {
      usleep(50000);
      zwlr_virtual_pointer_v1_button(pointer, milliseconds(), BTN_LEFT,
                                    WL_POINTER_BUTTON_STATE_PRESSED);
      zwlr_virtual_pointer_v1_frame(pointer);
      assert(wl_display_roundtrip(display) >= 0);
    }
    printf("POINT %u\n", count++);
    fflush(stdout);
    previous = elapsed;
  }
  assert(count >= 2 && feof(trace));
  fclose(trace);
  zwlr_virtual_pointer_v1_button(pointer, milliseconds(), BTN_LEFT,
                                WL_POINTER_BUTTON_STATE_RELEASED);
  zwlr_virtual_pointer_v1_frame(pointer);
  assert(wl_display_roundtrip(display) >= 0);
  puts("RELEASED");
  fflush(stdout);
  zwlr_virtual_pointer_v1_destroy(pointer);
  zwlr_virtual_pointer_manager_v1_destroy(manager);
  wl_display_flush(display);
  wl_display_disconnect(display);
  return 0;
}
