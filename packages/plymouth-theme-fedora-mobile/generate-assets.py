#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Render original theme artwork; PNGs are generated build artifacts, not sources."""
import argparse
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCALE = 4  # Antialias at build time; Plymouth applies the display's device scale.
BLUE = (81, 162, 218, 255)
WHITE = (244, 247, 250, 255)


def canvas(width, height):
    image = Image.new("RGBA", (width * SCALE, height * SCALE))
    return image, ImageDraw.Draw(image)


def box(coords):
    return tuple(round(n * SCALE) for n in coords)


def save(image, path):
    image.resize((image.width // SCALE, image.height // SCALE),
                 Image.Resampling.LANCZOS).save(path, optimize=True)


def font(size):
    path = subprocess.check_output(
        ["fc-match", "-f", "%{file}", "Cantarell:style=Regular"], text=True)
    return ImageFont.truetype(path, size * SCALE)


def generate(output):
    output.mkdir(parents=True, exist_ok=True)
    for frame in range(60):
        image, draw = canvas(240, 206)
        # A 104 px logical orbit: considerably larger than the desktop spinner.
        draw.ellipse(box((69, 7, 171, 109)), outline=(22, 38, 53, 255), width=3*SCALE)
        angle = frame * 360 / 60 - 90
        for step in range(100):
            tail = angle - 132 + step * 1.32
            brightness = step / 99
            color = tuple(round(a + (b-a)*brightness) for a, b in
                          zip((27, 57, 83), BLUE[:3])) + (255,)
            draw.arc(box((69, 7, 171, 109)), tail, tail + 3,
                     fill=color, width=4*SCALE)
        radians = math.radians(angle)
        x, y = 120 + 51*math.cos(radians), 58 + 51*math.sin(radians)
        draw.ellipse(box((x-3, y-3, x+3, y+3)), fill=(133, 205, 255, 255))
        draw.text((120*SCALE, 133*SCALE), "Fedora", font=font(32), anchor="mt", fill=WHITE)
        # Hand-spaced label avoids a second font and is independent of font kerning.
        label, label_font, tracking = "MOBILE", font(11), 4*SCALE
        widths = [draw.textlength(c, font=label_font) for c in label]
        x = (240*SCALE - sum(widths) - tracking*(len(label)-1)) / 2
        for character, width in zip(label, widths):
            draw.text((round(x), 177*SCALE), character, font=label_font,
                      fill=(162, 187, 208, 255), anchor="lt")
            x += width + tracking
        save(image, output / f"throbber-{frame+1:04}.png")

    # Plymouth's built-in entry text is black. Keep this field light, including
    # for visible answers, instead of creating an attractive but unreadable box.
    image, draw = canvas(220, 48)
    draw.rounded_rectangle(box((0.5, 0.5, 219.5, 47.5)), radius=9*SCALE,
                           fill=WHITE, outline=BLUE, width=2*SCALE)
    save(image, output / "entry.png")
    image, draw = canvas(14, 14)
    draw.ellipse(box((4, 4, 10, 10)), fill=(20, 34, 49, 255))
    save(image, output / "bullet.png")
    image, draw = canvas(40, 48)
    draw.arc(box((9, 7, 29, 31)), 180, 360, fill=WHITE, width=3*SCALE)
    draw.rounded_rectangle(box((5, 20, 33, 41)), radius=4*SCALE, fill=WHITE)
    draw.ellipse(box((17, 27, 21, 31)), fill=(20, 34, 49, 255))
    draw.line(box((19, 29, 19, 34)), fill=(20, 34, 49, 255), width=2*SCALE)
    save(image, output / "lock.png")
    image, draw = canvas(28, 24)
    draw.rounded_rectangle(box((1, 3, 26, 20)), radius=3*SCALE,
                           outline=WHITE, width=2*SCALE)
    for y in (8, 12):
        for x in (6, 11, 16, 21):
            draw.rectangle(box((x, y, x+1, y+1)), fill=WHITE)
    draw.line(box((8, 16, 19, 16)), fill=WHITE, width=2*SCALE)
    save(image, output / "keyboard.png")
    image, draw = canvas(26, 24)
    draw.polygon(box((13, 2, 23, 12, 18, 12, 18, 17, 8, 17, 8, 12, 3, 12)), fill=WHITE)
    draw.rounded_rectangle(box((8, 20, 18, 22)), radius=SCALE, fill=WHITE)
    save(image, output / "capslock.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    generate(parser.parse_args().output)
