#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef void MPPipeline;
typedef void (*MPPipelineCallback)(MPPipeline *, const void *);
typedef struct { uint32_t index; uint64_t generation; uint8_t *data; int fd; } MPBuffer;
static uint64_t stream_generation;
static void *mpcamera;
static MPPipeline *pipeline;
static unsigned queues, stops;
static unsigned char pending_data[sizeof(MPBuffer)];
static MPPipelineCallback pending_callback;
static void mp_camera_stop_capture(void *camera) { stops++; }
static void mp_camera_release_buffer(void *camera, uint32_t index) {
    assert(index == 2);
    queues++;
}
static void mp_pipeline_invoke(MPPipeline *pipe, MPPipelineCallback callback,
                               const void *data, size_t size) {
    assert(!pending_callback && size <= sizeof(pending_data));
    memcpy(pending_data, data, size);
    pending_callback = callback;
}
#include "stop.c"
#include "release.c"
static void return_later(void) {
#if GENERATION
    MPBuffer buffer = {.index=2, .generation=stream_generation};
    mp_io_pipeline_release_buffer(buffer);
#else
    (void)stream_generation;
    mp_io_pipeline_release_buffer(2);
#endif
}
static void dispatch_return(void) {
    /* Use aligned storage because the real GLib callback payload is aligned. */
    MPBuffer aligned;
    memcpy(&aligned, pending_data, sizeof(aligned));
    pending_callback(NULL, &aligned);
    pending_callback = NULL;
}
int main(void) {
    return_later();
    dispatch_return();
    assert(queues == 1);
    for (unsigned i=0; i<4; i++) {
        return_later();
        /* Pixel reads finish, but the return is still on the IO queue when
         * capture/preview mode or the selected camera is replaced. */
        stop_capture();
        dispatch_return();
        assert(queues == i + 1);
        return_later();
        dispatch_return();
        assert(queues == i + 2);
    }
    assert(stops == 4);
    puts("PASS: stopped-stream returns never requeue reused indices; current-stream returns still work");
}
