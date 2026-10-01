#!/usr/bin/env python3
"""Write a minimal EDID 1.3 block advertising only 1280x720@60 (CEA-861 VIC 4).

The DB410c's ADV7533 never sees HPD or an EDID from HDMI capture dongles that
do not assert hot-plug, so the liveboot initrd ships this block for the kernel's
drm.edid_firmware override. Generated rather than committed as a binary so the
timings are reviewable. Usage: gen-edid.py <output-file>
"""
import struct
import sys


def descriptor_dtd():
    # 74.25 MHz, 1280x720 active, 370x30 blanking, hsync +110/40, vsync +5/5,
    # 16:9 image size in mm, digital separate sync with positive polarities.
    pixel_clock = 7425  # in 10 kHz units
    hactive, hblank = 1280, 370
    vactive, vblank = 720, 30
    hsync_off, hsync_w = 110, 40
    vsync_off, vsync_w = 5, 5
    hsize_mm, vsize_mm = 0x20, 0x12  # nominal; the basic block already says 32x18 cm
    return bytes([
        pixel_clock & 0xff, pixel_clock >> 8,
        hactive & 0xff, hblank & 0xff, ((hactive >> 8) << 4) | (hblank >> 8),
        vactive & 0xff, vblank & 0xff, ((vactive >> 8) << 4) | (vblank >> 8),
        hsync_off & 0xff, hsync_w & 0xff,
        ((vsync_off & 0xf) << 4) | (vsync_w & 0xf),
        ((hsync_off >> 8) << 6) | ((hsync_w >> 8) << 4)
        | ((vsync_off >> 4) << 2) | (vsync_w >> 4),
        hsize_mm & 0xff, vsize_mm & 0xff, ((hsize_mm >> 8) << 4) | (vsize_mm >> 8),
        0, 0,
        0x1e,  # digital, separate sync, +vsync, +hsync
    ])


def descriptor_text(tag, text):
    body = text.encode("ascii")
    assert len(body) <= 13
    if len(body) < 13:
        body += b"\n" + b" " * (12 - len(body))
    return bytes([0, 0, 0, tag, 0]) + body


def descriptor_range_limits():
    # 50-75 Hz vertical, 30-80 kHz horizontal, 150 MHz max pixel clock, no GTF.
    return bytes([0, 0, 0, 0xfd, 0, 50, 75, 30, 80, 15, 0x0a]) + b" " * 7


def descriptor_dummy():
    return bytes([0, 0, 0, 0x10, 0]) + bytes(13)


def edid():
    block = bytearray()
    block += bytes([0x00, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x00])
    block += struct.pack(">H", (12 << 10) | (14 << 5) | 24)  # manufacturer "LNX"
    block += struct.pack("<H", 0)                            # product code
    block += struct.pack("<I", 0)                            # serial number
    block += bytes([5, 22])                                  # week 5 of 2012
    block += bytes([1, 3])                                   # EDID 1.3
    block += bytes([0x80, 0x20, 0x12, 0x78])                 # digital, 32x18 cm, gamma 2.2
    block += bytes([0x0a])                                   # RGB, preferred timing in DTD 1
    block += bytes([0xa2, 0x56, 0x4b, 0x9b, 0x26, 0x12, 0x50, 0x54, 0, 0])  # chromaticity
    block += bytes([0, 0, 0])                                # no established timings
    block += bytes([0x81, 0xc0]) + bytes([0x01, 0x01]) * 7   # standard timing 1280x720@60
    block += descriptor_dtd()
    block += descriptor_text(0xfc, "PocketFed HDM")
    block += descriptor_range_limits()
    block += descriptor_dummy()
    block += bytes([0])                                      # no extension blocks
    block += bytes([(-sum(block)) & 0xff])
    assert len(block) == 128 and sum(block) % 256 == 0
    return bytes(block)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: gen-edid.py <output-file>")
    with open(sys.argv[1], "wb") as f:
        f.write(edid())
