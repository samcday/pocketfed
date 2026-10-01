#!/usr/bin/env python3
"""Generate the public A4 camera target and a screen preview.

Requires Python reportlab and the Poppler pdftoppm command. No network access.
"""

import argparse
from pathlib import Path
import subprocess

import reportlab
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


PAYLOAD = "PocketFed sam-sargo camera test 2026-09-10"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "pdf"


def generate(output: Path) -> Path:
    fonts = Path(reportlab.__file__).resolve().parent / "fonts"
    pdfmetrics.registerFont(TTFont("TargetSans", str(fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("TargetSans-Bold", str(fonts / "VeraBd.ttf")))
    output.mkdir(parents=True, exist_ok=True)
    path = output / "pocketfed-camera-target.pdf"
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1, pageCompression=1)
    c.setTitle("PocketFed sam-sargo camera acceptance target")
    c.setAuthor("PocketFed")
    c.setSubject("Public printed-text, orientation, colour and QR camera target")
    width, height = A4
    left, right = 16 * mm, width - 16 * mm
    ink = colors.HexColor("#18313A")
    grey = colors.HexColor("#536069")

    def text(x, y, value, size=10, font="Helvetica", colour=colors.black):
        c.setFillColor(colour)
        c.setFont("TargetSans-Bold" if font == "Helvetica-Bold" else "TargetSans", size)
        c.drawString(x, y, value)

    def rule(y):
        c.setStrokeColor(colors.HexColor("#AAB4BA"))
        c.setLineWidth(0.5)
        c.line(left, y, right, y)

    # An asymmetric header makes rotation and mirroring immediately apparent.
    text(left, height - 20 * mm, "TOP / LEFT", 11, "Helvetica-Bold", ink)
    text(right - 53 * mm, height - 20 * mm, "A4 | PRINT AT 100%", 10, colour=grey)
    arrow_x, arrow_y = width / 2, height - 18 * mm
    c.setStrokeColor(ink)
    c.setLineWidth(2)
    c.line(arrow_x, arrow_y - 6 * mm, arrow_x, arrow_y + 2 * mm)
    c.line(arrow_x, arrow_y + 2 * mm, arrow_x - 2 * mm, arrow_y - mm)
    c.line(arrow_x, arrow_y + 2 * mm, arrow_x + 2 * mm, arrow_y - mm)
    rule(height - 28 * mm)
    text(left, height - 41 * mm, "PocketFed camera test", 25, "Helvetica-Bold", ink)
    text(left, height - 49 * mm, "sam-sargo / rear camera / target v1 / 2026-09-10", 10, colour=grey)

    text(left, height - 63 * mm, "READING TEXT", 10, "Helvetica-Bold", ink)
    paragraph = [
        "The camera should make everyday words",
        "easy to read. Place this page in even light.",
        "Focus on the text, save a photograph, and",
        "check the saved image at full resolution.",
    ]
    for index, line in enumerate(paragraph):
        text(left, height - 74 * mm - index * 7.5 * mm, line, 18)
    rule(height - 104 * mm)

    text(left, height - 115 * mm, "TEXT SIZE / DETAIL", 10, "Helvetica-Bold", ink)
    y = height - 126 * mm
    for size in (18, 16, 14, 12, 10):
        text(left, y, f"{size} pt", 9, "Helvetica-Bold", grey)
        text(left + 18 * mm, y, "Clear text: ABC xyz 0123456789", size)
        y -= 10 * mm
    rule(height - 171 * mm)

    # QR is a vector symbol with the standard four-module quiet zone.
    qr_size = 65 * mm
    qr_x, qr_y = right - qr_size, 49 * mm
    text(qr_x, qr_y + qr_size + 7 * mm, "SCAN / VERIFY EXACT PAYLOAD", 9, "Helvetica-Bold", ink)
    qr = QrCodeWidget(PAYLOAD, barLevel="M", barBorder=4)
    x0, y0, x1, y1 = qr.getBounds()
    qr_drawing = Drawing(
        qr_size, qr_size,
        transform=[qr_size / (x1 - x0), 0, 0, qr_size / (y1 - y0), 0, 0],
    )
    qr_drawing.add(qr)
    renderPDF.draw(qr_drawing, c, qr_x, qr_y)
    text(qr_x, qr_y - 4 * mm, "PocketFed sam-sargo camera test", 8)
    text(qr_x, qr_y - 8 * mm, "2026-09-10", 8)

    text(left, 121 * mm, "COLOUR / NEUTRAL STEPS", 10, "Helvetica-Bold", ink)
    swatches = [
        ("R", "#D63F3F"), ("G", "#319A55"), ("B", "#3569CE"),
        ("C", "#35B7C4"), ("M", "#AF459A"), ("Y", "#F2CB35"),
    ]
    swatch_size, gap = 13 * mm, 2 * mm
    for index, (label, value) in enumerate(swatches):
        x = left + index * (swatch_size + gap)
        c.setFillColor(colors.HexColor(value))
        c.rect(x, 99 * mm, swatch_size, 14 * mm, fill=1, stroke=0)
        text(x + 4.5 * mm, 94 * mm, label, 9)
    for index, value in enumerate((0, 64, 128, 192, 255)):
        x = left + index * 18 * mm
        c.setFillColor(colors.Color(value / 255, value / 255, value / 255))
        c.setStrokeColor(colors.HexColor("#808080"))
        c.setLineWidth(0.4)
        c.rect(x, 75 * mm, 16 * mm, 12 * mm, fill=1, stroke=1)
        text(x + 3 * mm, 70 * mm, str(value), 8)
    text(left, 61 * mm, "Compare with the actual printed page.", 9)
    text(left, 56 * mm, "Printer colour is not a calibrated reference.", 9)

    # A ruler checks that the printer did not silently scale to fit.
    text(left, 43 * mm, "50 mm at 100% print scale", 9, "Helvetica-Bold", ink)
    c.setLineWidth(0.8)
    c.setStrokeColor(colors.black)
    c.line(left, 37 * mm, left + 50 * mm, 37 * mm)
    for n in range(6):
        x = left + n * 10 * mm
        c.line(x, 35 * mm, x, 39 * mm)
    rule(29 * mm)
    text(left, 23 * mm, "Use the printed page for acceptance; a screen preview is only a setup aid.", 9)
    text(left, 18 * mm, "Keep every corner visible. Record the smallest readable text size and camera settings.", 9)
    text(left, 11 * mm, "BOTTOM / LEFT", 9, "Helvetica-Bold", ink)
    text(right - 28 * mm, 11 * mm, "BOTTOM / RIGHT", 9, "Helvetica-Bold", ink)
    c.showPage()
    c.save()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dpi", type=int, default=150, help="preview resolution (default: 150)")
    args = parser.parse_args()
    if not 72 <= args.dpi <= 600:
        parser.error("--dpi must be between 72 and 600")
    pdf = generate(args.output_dir.resolve())
    subprocess.run(
        ["pdftoppm", "-png", "-singlefile", "-r", str(args.dpi), str(pdf), str(pdf.with_suffix(""))],
        check=True,
    )
    print(pdf)
    print(pdf.with_suffix(".png"))


if __name__ == "__main__":
    main()
