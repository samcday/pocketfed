/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <stdbool.h>
#include "fpc1020.h"

struct fpc_sensor_device { int fd; };
int fpc_sensor_open(struct fpc_sensor_device *sensor, const char *path);
void fpc_sensor_close(struct fpc_sensor_device *sensor);
int fpc_sensor_reset(struct fpc_sensor_device *sensor);
int fpc_sensor_wakeup(struct fpc_sensor_device *sensor, bool enable);
int fpc_sensor_snapshot(struct fpc_sensor_device *sensor, struct fpc1020_irq_event *event);
/* 1=current high, 0=timeout, negative errno. cancel_fd may be -1. */
int fpc_sensor_wait_high(struct fpc_sensor_device *sensor, int timeout_ms, int cancel_fd);
