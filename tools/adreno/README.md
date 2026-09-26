# GTK rendering probe

A synthetic GTK4 workload for investigating [pocketfed#80](https://github.com/samcday/pocketfed/issues/80).
It animates twelve text tiles with gradients, rounded corners, shadows and opacity.
It needs GJS and GTK4 and runs 450 updates scheduled at 200 ms intervals: at least
90 seconds after startup, potentially longer under load. It prints progress every
50 timer callbacks. Timer progress alone does not prove that the GPU rendered frames.

Run inside the target Wayland session:

```sh
GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
FD_MESA_DEBUG=flush GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
FD_MESA_DEBUG=sysmem GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
FD_MESA_DEBUG=sysmem,flush GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
```

The sysmem pair holds direct rendering to system memory constant while toggling
flush-after-every-draw. Keep a working UART/recovery path available during hang tests.

Record the actual kernel and Mesa/GTK versions, display state, GPU runtime power
state, hardware EGL initialization, GPU fence progress and kernel hangchecks.
Distinguish application/compositor crashes from GPU hangs. This script does not
change power policy, select a display mode, or install a driver workaround.

The issue holds trial results and limitations. This is an experimental reduction
probe; its existence does not assert that it reproduces the Settings hang.
