# sdm670-early-nopdc

Diagnostic variant of `../sdm670-early`: identical sources except
`src/pinctrl-sdm670.c` sets `.wakeirq_map = NULL` / `.nwakeirq_map = 0`, so the
TLMM services every GPIO interrupt itself instead of routing wake-capable
pins through the PDC. Used to bisect the missing touchscreen interrupt on the
7.3-rc3 Fedora kernel (see hwe/evidence/2026-09-17-stock-rawhide-liveboot.md).
Not for deployment: it disables GPIO wakeup from suspend.
