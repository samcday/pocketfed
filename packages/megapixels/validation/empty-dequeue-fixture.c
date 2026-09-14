#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <linux/videodev2.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
typedef struct { uint32_t index; uint8_t *data; int fd; } MPBuffer;
struct mode { int format; uint32_t width, height; };
struct sensor { int video_fd; struct mode *current_mode; };
typedef struct { bool use_mplane; struct sensor *camera; struct { uint32_t length; uint8_t *data; int fd; } buffers[4]; } MPCamera;
typedef int GIOCondition;
struct capture_source_args { MPCamera *camera; void (*callback)(MPBuffer, void *); void *user_data; };
static bool frame_ready;
static unsigned int callbacks;
static uint8_t pixels[128];
static enum v4l2_buf_type get_buf_type(MPCamera *camera) { return camera->use_mplane ? V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE : V4L2_BUF_TYPE_VIDEO_CAPTURE; }
static void errno_printerr(const char *s) { perror(s); }
static uint32_t libmegapixels_mode_width_to_bytes(int format, uint32_t width) { return width * 2; }
static uint32_t libmegapixels_mode_width_to_padding(int format, uint32_t width) { return 0; }
static int xioctl(int fd, int request, void *argument)
{
    CHECK((unsigned int)request == VIDIOC_DQBUF);
    if (!frame_ready) { errno=EAGAIN; return -1; }
    struct v4l2_buffer *buf=argument;
    buf->index=2;
    if (buf->type==V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE) {
        CHECK(buf->length==1 && buf->m.planes);
        buf->m.planes[0].bytesused=sizeof(pixels);
    } else buf->bytesused=sizeof(pixels);
    frame_ready=false;
    return 0;
}
#include "dequeue.c"
#include "callback.c"
static void received(MPBuffer buffer, void *data)
{
    ++callbacks;
    CHECK(buffer.index==2 && buffer.data==pixels && buffer.fd==42);
}
int main(void)
{
    struct mode mode={.format=1,.width=8,.height=8};
    struct sensor sensor={.video_fd=10,.current_mode=&mode};
    MPCamera camera={.camera=&sensor};
    camera.buffers[2].length=sizeof(pixels);
    camera.buffers[2].data=pixels;
    camera.buffers[2].fd=42;
    struct capture_source_args args={.camera=&camera,.callback=received};
    for (int mplane=0;mplane<2;++mplane) {
        camera.use_mplane=mplane;
        callbacks=0;
        for (int i=0;i<512;++i) {
            CHECK(on_capture(10,1,&args));
            CHECK(callbacks==0);
        }
        frame_ready=true;
        CHECK(on_capture(10,1,&args));
        CHECK(callbacks==1);
        for (int i=0;i<512;++i) {
            CHECK(on_capture(10,1,&args));
            CHECK(callbacks==1);
        }
    }
    puts("Empty dequeue and valid-frame callback checks passed (single/multiplanar)");
    return 0;
}
