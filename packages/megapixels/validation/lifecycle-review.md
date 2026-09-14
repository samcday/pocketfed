# Megapixels 2.1 camera lifetime review

Source review on 2026-09-10. This is a review of upstream behavior, not a
record of device acceptance and not an applied lifecycle patch.

## Existing behavior

Megapixels 2.1 keeps the camera streaming when its window loses activity.
`on_frame()` in `src/io_pipeline.c:375` checks `check_window_active()` and
immediately returns the buffer when inactive and outside a still burst. It
does not issue `VIDIOC_STREAMOFF`, destroy the capture source, or close the
sensor/lens descriptors. Preview processing pauses; hardware capture does not.
The same code remains in current upstream `master` as fetched for this review.

The release build's `shutdown()` in `src/main.c:1527` explicitly delegates
cleanup to process exit. Its call to `mp_io_pipeline_stop()` is under
`#ifdef DEBUG`. Process exit closes descriptors through the kernel, so a
successful close-and-relaunch test can establish release without changing
this policy. Even the development stop function only destroys the capture
source and threads; it does not explicitly close the selected camera.

The existing camera-switch path in `src/io_pipeline.c:596` synchronizes image
processing, stops capture and calls `libmegapixels_close()`. The latter closes
the media, video, sensor, lens, flash and pipeline handle descriptors and
zeros them. These are reusable building blocks for a later pause operation.

Source references:

- [2.1 IO pipeline](https://gitlab.com/megapixels-org/Megapixels/-/blob/5fb1f24f1aeef80ea18224ab5829fda85653a4e8/src/io_pipeline.c)
- [2.1 application lifetime](https://gitlab.com/megapixels-org/Megapixels/-/blob/5fb1f24f1aeef80ea18224ab5829fda85653a4e8/src/main.c)
- [2.1 image processing](https://gitlab.com/megapixels-org/Megapixels/-/blob/5fb1f24f1aeef80ea18224ab5829fda85653a4e8/src/process_pipeline.c)
- [2.1 camera buffer and control workers](https://gitlab.com/megapixels-org/Megapixels/-/blob/5fb1f24f1aeef80ea18224ab5829fda85653a4e8/src/camera.c)
- [libmegapixels close implementation](https://gitlab.com/megapixels-org/libmegapixels/-/blob/d50bf166972df4252d127f72f90986892f3cd901/src/pipeline.c)
- [Current upstream IO pipeline](https://gitlab.com/megapixels-org/Megapixels/-/blob/master/src/io_pipeline.c)

## Patch boundary

There is no existing maintained background-release fix in the fetched
upstream files to backport. A window callback setting the IO camera to NULL
is insufficient: the process pipeline unconditionally dereferences the new
camera, and cached controls contain descriptor numbers that become invalid
after closing and reopening.

A bounded implementation would:

1. Keep the selected camera/configuration distinct from whether its devices
   are open. Transfer window activity from GTK's main thread to the IO thread
   instead of querying a GTK window from the frame thread.
2. Defer an ordinary background pause until an in-flight still burst finishes.
   The application's screen-flash window itself can take activity, which is
   why the existing frame filter exempts still capture.
3. Remove the capture source, synchronize pending image reads, finish/reap
   control workers, stop capture, and close the libmegapixels handles.
4. Reject buffer-return callbacks from the previous capture session. A
   processing sync alone is insufficient: it can queue buffer-return work
   back onto the IO thread while that thread waits for processing.
5. Reopen and select the preview mode, refresh control descriptors, preserve
   the user's focus/exposure requests, then restart capture and processing.
6. Treat system suspend explicitly. A direct suspend request need not first
   make the window inactive; using window activity alone cannot establish
   active-app suspend behavior.

This should be a separate reviewable change after the initial native app
capture trial. Normal regression coverage should exercise pause while idle,
pause during a still burst, rapid inactive/active transitions, rejection of
stale buffer returns, and refreshed control descriptors after reopening.
Device checks must verify descriptor release, resumed preview and another
saved still after app switching, lock/unlock and suspend/resume. Until those
checks pass, successful close/relaunch does not imply successful background
or active-app suspend behavior.
