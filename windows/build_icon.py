"""Build the Windows icon from the Hotspot Logger tower and contact-list mark."""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw


NAVY = "#063468"
CYAN = "#0ba4b3"
WHITE = "#ffffff"


def draw_icon(size=1024):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    scale = size / 1024

    def box(values):
        return tuple(round(value * scale) for value in values)

    def point(x, y):
        return round(x * scale), round(y * scale)

    draw.rounded_rectangle(box((38, 38, 986, 986)), radius=round(180 * scale), fill=NAVY)
    draw.ellipse(box((275, 230, 375, 330)), fill=WHITE)
    for bounds, width in [((185, 145, 465, 425), 45), ((115, 75, 535, 495), 45)]:
        draw.arc(box(bounds), 130, 230, fill=CYAN, width=round(width * scale))
        draw.arc(box(bounds), 310, 50, fill=CYAN, width=round(width * scale))

    draw.polygon([point(325, 315), point(150, 790), point(500, 790)], fill=WHITE)
    draw.rectangle(box((222, 535, 428, 580)), fill=NAVY)
    draw.rectangle(box((193, 630, 457, 675)), fill=NAVY)

    draw.rounded_rectangle(box((420, 445, 890, 805)), radius=round(52 * scale), fill=WHITE)
    for y in (535, 625, 715):
        draw.ellipse(box((475, y - 25, 525, y + 25)), fill=CYAN)
        draw.rounded_rectangle(box((555, y - 18, 825, y + 18)), radius=round(18 * scale), fill=NAVY)
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/branding"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    image = draw_icon()
    image.save(args.output / "hotspot-logger-icon.png", format="PNG")
    image.save(args.output / "hotspot-logger.ico", format="ICO",
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
