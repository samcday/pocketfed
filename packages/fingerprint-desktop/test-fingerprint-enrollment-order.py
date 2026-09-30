#!/usr/bin/env python3
"""Exercise the patched dialog's actual handoff functions with delayed D-Bus replies."""
import argparse
from pathlib import Path
import re
import resource
import signal
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--old-ordering', action='store_true')
a = p.parse_args()
s = a.source.read_text()
names = ['update_dialog_state', 'add_dialog_state', 'remove_dialog_state',
         'cancel_pending_enrollment', 'start_pending_enrollment',
         'identification_stop_cb', 'stop_identification', 'enroll_finger',
         'cancel_button_clicked_cb']
functions = []
for name in names:
    match = re.search(r'^static [^\n]+\n' + name + r'\s*\(.*?^}', s, re.M | re.S)
    assert match, name
    functions.append(match.group())
if a.old_ordering:
    functions[-2] = functions[-2].replace('    start_pending_enrollment (self);',
        '    cc_fprintd_device_call_enroll_start (self->device, finger_id, G_DBUS_CALL_FLAGS_NONE, -1, self->cancellable, enroll_start_cb, self);')
state = re.search(r'typedef enum \{\n    DIALOG_STATE_NONE.*?\} DialogState;', s, re.S).group()
prefix = r'''
#include <gio/gio.h>
#include <assert.h>
#include <stdio.h>
#define _(x) (x)
#define GTK_WIDGET(x) (x)
#define ADW_STATUS_PAGE(x) (x)
#define CC_FPRINTD_DEVICE(x) ((CcFprintdDevice *)(x))
typedef GObject CcFprintdDevice;
typedef struct {
 DialogState dialog_state;
 CcFprintdDevice *device;
 GCancellable *cancellable;
 char *pending_enroll_finger;
 void *spinner, *stack, *enrollment_view, *prints_manager, *progress_bar;
 double enroll_progress;
 unsigned enroll_stages_passed;
} CcFingerprintDialog;
#define ENROLL_STATE_NORMAL 0
static unsigned enrolls, stops, resumes, errors, enroll_stops;
static char *enrolled;
static GAsyncReadyCallback stop_callback;
static gpointer stop_data;
static GError *stop_error;
static void gtk_widget_set_visible(void *w, gboolean b) {(void)w;(void)b;}
static void gtk_stack_set_visible_child(void *w, void *c) {(void)w;(void)c;}
static void gtk_progress_bar_set_fraction(void *w, double d) {(void)w;(void)d;}
static void adw_status_page_set_title(void *w, const char *t) {(void)w;(void)t;}
static char *get_enrollment_string(CcFingerprintDialog *s, const char *f) {(void)s;return g_strdup(f);}
static void set_enroll_result_message(CcFingerprintDialog *s, int e, const char *m) {(void)s;(void)e;(void)m;}
static const char *dbus_error_to_human(CcFingerprintDialog *s, GError *e) {(void)s;return e->message;}
static void notify_error(CcFingerprintDialog *s, const char *m) {(void)s;(void)m;++errors;}
static void maybe_start_identification(CcFingerprintDialog *s) {(void)s;++resumes;}
static void enroll_stop(CcFingerprintDialog *s) {(void)s;++enroll_stops;}
static void enroll_start_cb(GObject *o, GAsyncResult *r, gpointer d) {(void)o;(void)r;(void)d;}
static void cc_fprintd_device_call_enroll_start(CcFprintdDevice *d, const char *f,
 GDBusCallFlags flags, int timeout, GCancellable *c, GAsyncReadyCallback cb, gpointer data)
{(void)d;(void)flags;(void)timeout;(void)c;(void)cb;(void)data;++enrolls;g_free(enrolled);enrolled=g_strdup(f);}
static void cc_fprintd_device_call_verify_stop(CcFprintdDevice *d, GDBusCallFlags flags,
 int timeout, GCancellable *c, GAsyncReadyCallback cb, gpointer data)
{(void)d;(void)flags;(void)timeout;(void)c;++stops;stop_callback=cb;stop_data=data;}
static gboolean cc_fprintd_device_call_verify_stop_finish(CcFprintdDevice *d,
 GAsyncResult *r, GError **error)
{(void)d;(void)r;if(stop_error){*error=g_error_copy(stop_error);return FALSE;}return TRUE;}
static void start_pending_enrollment(CcFingerprintDialog *self);
static gboolean cancel_pending_enrollment(CcFingerprintDialog *self);
static void stop_identification(CcFingerprintDialog *self);
'''
epilogue = r'''
static void begin(CcFingerprintDialog *s, gboolean verifying)
{
 *s=(CcFingerprintDialog){.dialog_state=DIALOG_STATE_DEVICE_CLAIMED,
  .device=g_object_new(G_TYPE_OBJECT,NULL),.cancellable=g_cancellable_new()};
 if(verifying)s->dialog_state|=DIALOG_STATE_DEVICE_VERIFYING;
 enrolls=stops=resumes=errors=enroll_stops=0;stop_callback=NULL;stop_data=NULL;
 g_clear_error(&stop_error);g_clear_pointer(&enrolled,g_free);
}
static void finish_stop(CcFingerprintDialog *s)
{assert(stop_callback);stop_callback(G_OBJECT(s->device),NULL,stop_data);}
static void end(CcFingerprintDialog *s)
{cancel_pending_enrollment(s);g_clear_object(&s->device);g_clear_object(&s->cancellable);}
int main(void)
{
 CcFingerprintDialog s;
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");
 assert(stops==1 && enrolls==0);finish_stop(&s);
 assert(enrolls==1 && !s.pending_enroll_finger && resumes==0);
 assert(!g_strcmp0(enrolled,"left-index-finger"));end(&s);
 begin(&s,TRUE);stop_identification(&s);enroll_finger(&s,"right-thumb");
 assert(stops==1 && enrolls==0);finish_stop(&s);assert(enrolls==1);end(&s);
 begin(&s,FALSE);enroll_finger(&s,"left-thumb");assert(stops==0 && enrolls==1);end(&s);
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");cancel_button_clicked_cb(&s);
 assert(!g_cancellable_is_cancelled(s.cancellable) && enroll_stops==0);
 finish_stop(&s);assert(enrolls==0 && !s.pending_enroll_finger);end(&s);
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");
 /* Dialog close, screen lock and device loss discard the queued intent. */
 assert(cancel_pending_enrollment(&s));finish_stop(&s);assert(enrolls==0);end(&s);
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");
 stop_error=g_error_new_literal(G_IO_ERROR,G_IO_ERROR_FAILED,"stop failed");
 finish_stop(&s);assert(enrolls==0 && errors==1 && !s.pending_enroll_finger);end(&s);
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");g_cancellable_cancel(s.cancellable);
 finish_stop(&s);assert(enrolls==0 && !s.pending_enroll_finger);end(&s);
 begin(&s,TRUE);enroll_finger(&s,"left-index-finger");s.dialog_state&=~DIALOG_STATE_DEVICE_CLAIMED;
 finish_stop(&s);assert(enrolls==0 && !s.pending_enroll_finger);end(&s);
 g_clear_error(&stop_error);g_clear_pointer(&enrolled,g_free);
 puts("PASS: delayed and already-pending VerifyStop, immediate first enrollment, cancellation, close, stop failure and lost claim");
}
'''
a.output.mkdir(parents=True, exist_ok=True)
code = '#include <gio/gio.h>\n' + state + '\n' + prefix + '\n\n'.join(functions) + epilogue
(a.output / 'test-enrollment-order.c').write_text(code)
flags = subprocess.check_output(['pkg-config','--cflags','--libs','gio-2.0'],text=True).split()
subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(a.output/'test-enrollment-order.c'),*flags,'-o',str(a.output/'test-enrollment-order')],check=True)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
result = subprocess.run([str(a.output/'test-enrollment-order')])
if a.old_ordering:
    assert result.returncode == -signal.SIGABRT, 'unfixed ordering did not reach the regression assertion'
    print('PASS: original immediate-EnrollStart ordering rejected by the regression test')
else:
    assert result.returncode == 0
