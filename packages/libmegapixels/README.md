# libmegapixels

Pinned upstream 0.2.3 includes the Pixel 3a camera configuration. The package
adds a relative `google,sargo.conf` symlink so current mainline device trees
select the existing upstream configuration. Its `-devel` package exposes
pkg-config ABI version 1.1.0. Release 2 orders the rear camera first in this
configuration so Megapixels opens it by default. The existing configuration
lint check also asserts this discovery order. See
[`../megapixels/README.md`](../megapixels/README.md) for source pins and builds.

Release 3 matches a sensor's flip controls to the configured Bayer order before
propagating formats downstream. The IMX363 starts with both flips enabled and
reports BGGR10, while this configuration requests RGGB10. Previously the sensor
format was rejected and STREAMON failed with EPIPE; an earlier libcamera run
hid the problem by clearing the flips. A manual flip correction established
real DNG/JPEG capture through the unchanged Megapixels release-4 app.

The fix changes only the needed sensor layout controls, retries TRY format,
preserves matching layouts, and restores partial writes when a control is
unavailable or busy. It does not change the public ABI or configuration syntax.
The regression checks all four Bayer orders for 8/10/12/14/16-bit formats,
unsupported formats, bit-depth mismatches and rollback. Native build and checks
passed. A device trial starting with both default flips enabled corrected the
layout automatically and reached STREAMON without EPIPE. No frames arrived,
however; the same stall reproduced with release 2 and later with libcamera.
This establishes layout correction, not a successful cold-start capture.
