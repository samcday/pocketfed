# GTK rendering probe

A synthetic GTK4 workload for investigating [pocketfed#80](https://github.com/samcday/pocketfed/issues/80).
It animates twelve text tiles with gradients, rounded corners, shadows and opacity.
It needs GJS and GTK4, runs for approximately 90 seconds, and prints progress every
50 timer callbacks. Timer progress alone does not prove that the GPU rendered frames.

Run inside the target Wayland session:

```sh
GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
FD_MESA_DEBUG=flush GDK_BACKEND=wayland GSK_RENDERER=gl GDK_DEBUG=opengl gjs gtk-probe.js
```

Record the actual kernel and Mesa/GTK versions, display state, GPU runtime power
state, hardware EGL initialization, GPU fence progress and kernel hangchecks.
Distinguish application/compositor crashes from GPU hangs. This script does not
change power policy, select a display mode, or install a driver workaround.

The issue holds trial results and limitations. This is an experimental reduction
probe; its existence does not assert that it reproduces the Settings hang.
