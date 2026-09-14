#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <math.h>
#include <time.h>
#include <linux/videodev2.h>
#define MAX(a,b) ((a) > (b) ? (a) : (b))
typedef void MPPipeline;
struct _MPPipeline;
typedef struct { int id, value; } MPControl;
typedef struct {
    MPControl control, auto_control;
    int value, min, max;
    bool manual;
} controlstate;
typedef struct {
    void *camera, *configuration, *mode_capture;
    int burst_length, captures_remaining, counter;
    int preview_width, preview_height, device_rotation, device_accel_rotation;
    bool device_accel_rotation_good, has_auto_focus_start, can_af_trigger;
    bool flash_enabled, flush_pipeline;
    float balance[3];
    controlstate gain, dgain, exposure, focus, red, blue;
} mp_state_proc;
static mp_state_proc state_io, state_proc;
static bool pipeline_changed;
static int publications, setups, starts;
static void *mpcamera;
static int mp_camera_control_get_int32(MPControl *control) { return control->value; }
static void mp_camera_control_set_int32(MPControl *control, int value) {}
static void mp_process_pipeline_sync(void) {}
void mp_camera_stop_capture(void *camera) {}
void stop_capture(void) {}
static void libmegapixels_select_mode(void *camera, void *mode, struct v4l2_format *format) {}
static void mp_camera_start_capture(void *camera) { starts++; }
static void mp_flash_enable(void *camera) {}
static void setup_capture(void) { setups++; }
static void mp_process_pipeline_update_state(const mp_state_proc *next) {
    state_proc.burst_length = next->burst_length;
    publications++;
}
#include "publish.c"
#define capture capture_process
#include "capture-process.c"
#undef capture
static void mp_process_pipeline_capture(void) {
    /* State publication must precede capture, as on the GLib process queue. */
    assert(publications == 1);
    capture_process(NULL, NULL);
}
#define capture capture_io
#include "capture-io.c"
#undef capture
int main(void) {
    /* A clean inactive preview is the phone failure; a dirty preview is the
     * other normal path. Repeated captures must propagate changed burst sizes. */
    for (int dirty = 0; dirty < 2; dirty++) {
        const int gains[] = {0, 480, 120, 0};
        for (unsigned i = 0; i < sizeof(gains)/sizeof(gains[0]); i++) {
            pipeline_changed = dirty;
            state_io.gain.max = 480;
            state_io.gain.control = (MPControl){1, gains[i]};
            state_io.dgain.control = (MPControl){2, 1024};
            state_proc.counter = 99;
            publications = setups = starts = 0;
            capture_io(NULL, NULL);
            int expected = (int)fmax(sqrtf((float)gains[i]/480) * 10, 2) + 1;
            assert(state_io.captures_remaining == expected);
            assert(state_proc.captures_remaining == expected);
            assert(state_proc.counter == 0);
            assert(publications == 1 && setups == 1 && starts == 1);
        }
    }
    puts("PASS: clean and dirty preview states publish every burst length before processing capture");
}
