// SPDX-License-Identifier: MIT
// Exercise focus writes while keeping one lens descriptor open across autosuspend.
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static int failure(int fd, const char *operation)
{
    perror(operation);
    close(fd);
    return 1;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "Usage: %s /dev/v4l-subdevN\n", argv[0]);
        return 2;
    }
    int fd = open(argv[1], O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        perror("open lens");
        return 1;
    }
    struct v4l2_queryctrl limits = {.id = V4L2_CID_FOCUS_ABSOLUTE};
    struct v4l2_control control = {.id = V4L2_CID_FOCUS_ABSOLUTE};
    if (ioctl(fd, VIDIOC_QUERYCTRL, &limits) < 0 || ioctl(fd, VIDIOC_G_CTRL, &control) < 0)
        return failure(fd, "read focus range/state");
    int initial = control.value;
    int values[] = {initial, initial + 256, initial - 256, initial};
    printf("range=%d..%d initial=%d\n", limits.minimum, limits.maximum, initial);
    for (unsigned int i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        int value = values[i];
        if (value < limits.minimum) value = limits.minimum;
        if (value > limits.maximum) value = limits.maximum;
        control.value = value;
        if (ioctl(fd, VIDIOC_S_CTRL, &control) < 0)
            return failure(fd, "set focus");
        struct timespec delay = {.tv_sec = 1, .tv_nsec = 300000000};
        while (nanosleep(&delay, &delay) < 0) {
            if (errno != EINTR) return failure(fd, "focus hold");
        }
        if (ioctl(fd, VIDIOC_G_CTRL, &control) < 0)
            return failure(fd, "read focus after hold");
        if (control.value != value) {
            fprintf(stderr, "Focus changed: requested %d, read %d\n", value, control.value);
            close(fd);
            return 1;
        }
        printf("focus=%d after=1.3s\n", control.value);
        fflush(stdout);
    }
    return close(fd) < 0 ? 1 : 0;
}
