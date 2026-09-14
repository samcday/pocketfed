
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <linux/videodev2.h>
#define TRUE true
#define GL_RGBA 0
#define GL_UNSIGNED_BYTE 0
#define g_malloc_n(n, m) calloc(n, m)
#define g_free free
typedef struct { int id, fd, min, max, default_value; } MPControl;
typedef struct { MPControl control; int value, value_req, min, max; bool manual, manual_req; MPControl auto_control; } controlstate;
typedef struct { int exposure, blacklevel; float avg_r, avg_g, avg_b; } stats_t;
static struct {
    controlstate exposure, gain, dgain, focus;
    stats_t stats;
    struct { float color_matrix_1[9], color_matrix_2[9]; } calibration;
    float blacklevel, red, blue;
} state_proc;
static int output_buffer_width = 30, output_buffer_height = 90, exposure_limit = 907;
static void *gles2_debayer;
static int writes[4], direction = 1, write_count;
static void record_write(MPControl *ctrl, int value) {
    assert(ctrl->id != 0);
    assert(value >= ctrl->min && value <= ctrl->max);
    int index = ctrl->id == V4L2_CID_ANALOGUE_GAIN ? 1 :
                ctrl->id == V4L2_CID_DIGITAL_GAIN ? 2 :
                ctrl->id == V4L2_CID_EXPOSURE ? 3 : 0;
    writes[index] = value;
    write_count++;
}
struct focus_stats { int unused; };
static void mp_io_pipeline_set_control_int32(MPControl *ctrl, int value) { record_write(ctrl, value); }
static void glReadPixels(int x, int y, int w, int h, int a, int b, void *c) { (void)x; (void)y; (void)w; (void)h; (void)a; (void)b; (void)c; }
static void libmegapixels_aaa_set_matrix(stats_t *s, float *a, float *b) { (void)s; (void)a; (void)b; }
static void libmegapixels_aaa_software_statistics(stats_t *s, void *f, int w, int h) { (void)f; (void)w; (void)h; s->exposure = direction; }
static void focus_stats(struct focus_stats *s, void *p, int w, int h) { (void)s; (void)p; (void)w; (void)h; }
static void auto_focus_step(struct focus_stats *s) { (void)s; }
static void gles2_debayer_set_shading(void *d, float r, float b, float l) { (void)d; (void)r; (void)b; (void)l; }

static struct {
    struct { int sensor_fd, lens_fd; } *camera;
    controlstate exposure, gain, dgain, focus, red, blue;
    int captures_remaining;
    bool trigger_af, can_af_trigger;
} state_io;
static bool pipeline_changed;
static void *mpcamera;
static bool front_sensor;
static void update_process_pipeline(void) {}
static void start_focus(void) {}
static bool mp_camera_query_control(int fd, int id, MPControl *control) {
    int min=0, max=0, value=0;
    if (id == V4L2_CID_FOCUS_ABSOLUTE && !front_sensor) {
        max=1023; value=288;
    } else if (id == V4L2_CID_ANALOGUE_GAIN) {
        max=front_sensor ? 960 : 480;
    } else if (id == V4L2_CID_DIGITAL_GAIN && !front_sensor) {
        max=4096; value=1024;
    } else if (id == V4L2_CID_EXPOSURE) {
        min=front_sensor ? 1 : 4; max=front_sensor ? 2544 : 3062;
        value=front_sensor ? 1000 : 1600;
    } else { return false; }
    if (control) *control = (MPControl){ .id=id, .fd=fd, .min=min, .max=max, .default_value=value };
    return true;
}
static int mp_camera_control_get_int32(MPControl *control) { return control->default_value; }
static bool mp_camera_control_get_bool(MPControl *control) { return control->default_value != 0; }
static int mp_camera_control_set_int32_bg(void *camera, MPControl *control, int value) { (void)camera; record_write(control,value); return 0; }
static int mp_camera_control_set_bool_bg(void *camera, MPControl *control, bool value) { return mp_camera_control_set_int32_bg(camera,control,value); }

static struct { controlstate gain, exposure, focus; } state;
static int ui_updates;
static void update_io_pipeline(void) { ui_updates++; }

#include "control-functions.c"

static void sensor_state(void) {
    static typeof(*state_io.camera) camera = { .sensor_fd=10, .lens_fd=11 };
    state_io.camera = &camera;
    init_controls();
    state_proc.gain = state_io.gain;
    state_proc.dgain = state_io.dgain;
    state_proc.exposure = state_io.exposure;
    state_proc.focus = state_io.focus;
    state_proc.focus.manual = true;
    state_proc.red = state_proc.blue = 1;
    write_count = 0;
    for (int i=0; i<4; i++) writes[i]=-1;
}
int main(void) {
    sensor_state();
    assert(state_io.dgain.value == 1024 && state_io.dgain.value_req == 1024);
    assert(state_io.exposure.min == 4 && state_io.exposure.value_req == 1600);
    /* Unset old requests must never overwrite other measured controls. */
    state_proc.gain.value_req = state_proc.dgain.value_req = state_proc.exposure.value_req = 0;
    process_aaa();
    assert(write_count == 1 && writes[1] == 4 && writes[2] == -1 && writes[3] == -1);
    assert(state_proc.dgain.value == 1024 && state_proc.exposure.value == 1600);
    puts("PASS: first dark frame changes only analogue gain, preserving digital gain and exposure");

    sensor_state(); direction = 0;
    state_proc.gain.value_req = state_proc.dgain.value_req = state_proc.exposure.value_req = 0;
    process_aaa();
    assert(write_count == 0);
    puts("PASS: first neutral frame emits no control writes");

    sensor_state(); direction = -1;
    state_proc.dgain.value = state_proc.dgain.min;
    state_proc.exposure.value = 4;
    process_aaa();
    assert(write_count == 0 && state_proc.exposure.value == 4);
    puts("PASS: exposure at the sensor minimum never emits an invalid zero write");

    sensor_state(); direction = 1;
    state_proc.gain.manual = true;
    process_aaa();
    assert(write_count == 1 && writes[1] == -1 && writes[2] == -1 && writes[3] == 2000);
    puts("PASS: automatic exposure preserves manual analogue gain");

    sensor_state();
    state_io.gain.value=4; state_io.gain.value_req=0;
    state_io.focus.value=300; state_io.focus.value_req=288;
    update_controls();
    assert(write_count == 0);
    puts("PASS: the IO thread does not overwrite software AE/AF requests");

    state_io.exposure.manual_req=true;
    state_io.exposure.value_req=800;
    update_controls();
    assert(write_count == 1 && writes[3] == 800);
    puts("PASS: manual exposure works without a hardware auto-exposure control");

    /* Reuse the IO state with a different sensor, including missing controls. */
    front_sensor=true;
    sensor_state();
    assert(state_io.dgain.control.id == 0 && state_io.dgain.max == 0 && state_io.dgain.value_req == 0);
    assert(state_io.focus.control.id == 0 && state_io.focus.max == 0 && state_io.focus.value_req == 0);
    assert(state_io.exposure.min == 1 && state_io.exposure.max == 2544 && state_io.exposure.value_req == 1000);
    assert(!state_io.exposure.manual && !state_io.exposure.manual_req);
    update_control(&state_proc.dgain);
    assert(write_count == 0);
    puts("PASS: changing sensors resets controls, limits, requests and manual flags; absent controls emit no writes");

    state.gain.value=8; state.exposure.value=1600; state.focus.value=300;
    set_gain_auto(false); set_shutter_auto(false); set_focus_auto(false);
    assert(ui_updates == 3);
    assert(state.gain.manual_req && state.gain.value_req == 8);
    assert(state.exposure.manual_req && state.exposure.value_req == 1600);
    assert(state.focus.manual_req && state.focus.value_req == 300);
    puts("PASS: switching to manual mode preserves the current gain, exposure and focus");
}
