#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <linux/videodev2.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define CHECK(condition) do { \
        if (!(condition)) { \
                fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
                exit(EXIT_FAILURE); \
        } \
} while (0)

/* Only the callback's collaborators are substituted, never its decisions. */
typedef struct {
        uint32_t index;
        uint64_t generation;
        uint8_t *data;
        int fd;
} MPBuffer;

typedef struct {
        int width;
        int height;
} libmegapixels_mode;

typedef struct {
        libmegapixels_mode *current_mode;
} libmegapixels_camera;

typedef struct {
        bool manual;
        int auto_control;
} fixture_control;

static struct {
        bool flush_pipeline;
        int blank_frame_count;
        int captures_remaining;
        bool flash_enabled;
        fixture_control exposure;
        fixture_control gain;
        libmegapixels_camera *camera;
        libmegapixels_mode *mode_preview;
} state_io;

static libmegapixels_mode mode = { .width = 4032, .height = 3024 };
static libmegapixels_camera camera = { .current_mode = &mode };
static void *mpcamera = &camera;
static bool pipeline_changed;
static uint64_t stream_generation;
static bool window_active;
static bool queued[MAX_VIDEO_BUFFERS];
static unsigned int queue_depth;
static unsigned int issued;
static unsigned int released;
static unsigned int processed;
static unsigned int stops;
static unsigned int starts;
static unsigned int mode_changes;
static unsigned int synchronizations;
static unsigned int flash_disables;
static unsigned int state_updates;
static unsigned int control_updates;

static bool check_window_active(void)
{
        return window_active;
}

/* External linkage also permits testing a source version without this call. */
void do_aaa(void) {}
static void update_controls(void) { ++control_updates; }

static void mp_io_pipeline_release_buffer(MPBuffer buffer)
{
        uint32_t index = buffer.index;
        CHECK(buffer.generation == stream_generation);
        CHECK(index < MAX_VIDEO_BUFFERS);
        CHECK(!queued[index]);
        queued[index] = true;
        ++queue_depth;
        ++released;
}

static void mp_process_pipeline_process_image(MPBuffer buffer)
{
        ++processed;
        /* Production processing releases the input after copying its pixels. */
        mp_io_pipeline_release_buffer(buffer);
}

static void mp_process_pipeline_sync(void)
{
        CHECK(queue_depth == MAX_VIDEO_BUFFERS);
        ++synchronizations;
}

static void stop_capture(void)
{
        ++stream_generation;
        CHECK(queue_depth == MAX_VIDEO_BUFFERS);
        ++stops;
}

static void libmegapixels_select_mode(libmegapixels_camera *camera,
                                     libmegapixels_mode *mode,
                                     struct v4l2_format *format)
{
        ++mode_changes;
}

static void mp_camera_start_capture(void *camera) { ++starts; }
static void mp_flash_disable(libmegapixels_camera *camera) { ++flash_disables; }
static void update_process_pipeline(void) { ++state_updates; }
static void mp_camera_control_set_int32_bg(void *camera, int *control, int value) {}
static void mp_camera_control_set_bool_bg(void *camera, int *control, bool value) {}

#include "on-frame.c"

static void reset(bool active)
{
        memset(&state_io, 0, sizeof(state_io));
        state_io.camera = &camera;
        state_io.mode_preview = &mode;
        state_io.flush_pipeline = true;
        for (unsigned int i = 0; i < MAX_VIDEO_BUFFERS; ++i)
                queued[i] = true;
        queue_depth = MAX_VIDEO_BUFFERS;
        issued = released = processed = 0;
        stops = starts = mode_changes = synchronizations = 0;
        flash_disables = state_updates = control_updates = 0;
        pipeline_changed = false;
        window_active = active;
}

static void deliver(bool blank)
{
        uint8_t pixels[100] = { 0 };
        if (!blank)
                pixels[50] = 1;
        unsigned int index = issued % MAX_VIDEO_BUFFERS;
        CHECK(queued[index]);
        queued[index] = false;
        --queue_depth;
        ++issued;
        MPBuffer buffer = { .index = index, .data = pixels, .fd = -1 };
        on_frame(buffer, NULL);
        CHECK(queue_depth == MAX_VIDEO_BUFFERS);
        CHECK(released == issued);
}

int main(void)
{
        /* More blank frames than buffers must reach the existing fallback. */
        reset(true);
        for (unsigned int i = 0; i < 2 * MAX_VIDEO_BUFFERS + 1; ++i)
                deliver(true);
        CHECK(!state_io.flush_pipeline);
        CHECK(state_io.blank_frame_count == 0);
        CHECK(processed > 0);
        CHECK(processed < issued);
        unsigned int previously_processed = processed;
        deliver(false);
        CHECK(processed == previously_processed + 1);
        CHECK(starts == 0 && stops == 0);

        /* An inactive preview releases frames without advancing its flush. */
        reset(false);
        for (unsigned int i = 0; i < MAX_VIDEO_BUFFERS + 1; ++i)
                deliver(true);
        CHECK(processed == 0 && control_updates == 0);
        CHECK(state_io.flush_pipeline && state_io.blank_frame_count == 0);

        /* Capture runs while inactive; rejected frames do not consume a shot. */
        reset(false);
        state_io.captures_remaining = 2;
        state_io.flash_enabled = true;
        for (int i = 0; i < 3; ++i) {
                deliver(true);
                CHECK(state_io.captures_remaining == 2);
                CHECK(processed == 0);
        }
        deliver(false);
        CHECK(state_io.captures_remaining == 1 && processed == 1);
        CHECK(!state_io.flush_pipeline && state_io.blank_frame_count == 0);
        deliver(false);
        CHECK(state_io.captures_remaining == 0 && processed == 2);
        CHECK(starts == 1 && stops == 1 && mode_changes == 1);
        CHECK(synchronizations == 1 && flash_disables == 1 && state_updates == 1);
        CHECK(state_io.flush_pipeline);

        /* The same bounded fallback must work on return to active preview. */
        window_active = true;
        for (unsigned int i = 0; i < 2 * MAX_VIDEO_BUFFERS + 1; ++i)
                deliver(true);
        CHECK(!state_io.flush_pipeline && state_io.blank_frame_count == 0);
        CHECK(processed > 2);
        CHECK(starts == 1 && stops == 1);

        puts("PASS: finite buffer queue survives blank-frame fallback, inactive preview, and capture-to-preview transition");
        return 0;
}
