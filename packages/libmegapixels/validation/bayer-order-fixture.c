#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <linux/v4l2-subdev.h>
#define log_error(...) fprintf(stderr, __VA_ARGS__)
static int flips[2], gets, sets, missing_axis, fail_axis;
static int xioctl(int fd, unsigned long request, void *argument) {
    struct v4l2_control *control = argument;
    assert(fd == 42);
    int axis = control->id == V4L2_CID_HFLIP ? 0 : 1;
    assert(control->id == (axis ? V4L2_CID_VFLIP : V4L2_CID_HFLIP));
    if (request == VIDIOC_G_CTRL) {
        gets++;
        if (axis == missing_axis) { errno=EINVAL; return -1; }
        control->value = flips[axis];
    } else {
        assert(request == VIDIOC_S_CTRL);
        sets++;
        if (axis == fail_axis) { errno=EBUSY; return -1; }
        flips[axis] = control->value;
    }
    return 0;
}
#include "bayer-order.c"
#define FORMATS(bits) {MEDIA_BUS_FMT_SRGGB##bits##_1X##bits, MEDIA_BUS_FMT_SGRBG##bits##_1X##bits, MEDIA_BUS_FMT_SGBRG##bits##_1X##bits, MEDIA_BUS_FMT_SBGGR##bits##_1X##bits}
static const uint32_t formats[][4] = {FORMATS(8), FORMATS(10), FORMATS(12), FORMATS(14), FORMATS(16)};
static void reset(int h, int v) {
    flips[0]=h; flips[1]=v;
    gets=sets=0; missing_axis=fail_axis=-1;
}
int main(void) {
    /* In an RGGB 2x2 sample, moving the red pixel to column 1/row 1 requires
     * the corresponding horizontal/vertical flip. Check all starting states. */
    for (unsigned depth=0; depth<sizeof(formats)/sizeof(formats[0]); depth++) {
        for (unsigned original=0; original<4; original++) {
            for (unsigned wanted=0; wanted<4; wanted++) {
                reset(original%2, original/2);
                assert(match_bayer_order(42, formats[depth][original], formats[depth][wanted]));
                assert(flips[0] == (int)(wanted%2) && flips[1] == (int)(wanted/2));
                if (original==wanted) assert(gets==0 && sets==0);
            }
        }
    }
    reset(1,1);
    assert(!match_bayer_order(42, MEDIA_BUS_FMT_UYVY8_1X16, MEDIA_BUS_FMT_SRGGB10_1X10));
    assert(!match_bayer_order(42, MEDIA_BUS_FMT_SBGGR10_1X10, MEDIA_BUS_FMT_SRGGB12_1X12));
    assert(gets==0 && sets==0 && flips[0]==1 && flips[1]==1);

    for (int axis=0; axis<2; axis++) {
        reset(1,1); missing_axis=axis;
        assert(!match_bayer_order(42, MEDIA_BUS_FMT_SBGGR10_1X10, MEDIA_BUS_FMT_SRGGB10_1X10));
        assert(flips[0]==1 && flips[1]==1);
        reset(1,1); fail_axis=axis;
        assert(!match_bayer_order(42, MEDIA_BUS_FMT_SBGGR10_1X10, MEDIA_BUS_FMT_SRGGB10_1X10));
        assert(flips[0]==1 && flips[1]==1);
    }
    puts("PASS: all Bayer layouts/depths, unchanged layouts, unsupported formats and rollback on unavailable/busy controls");
}
