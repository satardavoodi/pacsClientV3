"""One-off: build a small side-by-side montage of the four YBR interpretations."""
import os

from PIL import Image, ImageDraw

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
OUT = os.path.join(ROOT, "user_data", "_ybr_repro")
LABELS = {
    "A": "A  today (pydicom 422 expand)",
    "B": "B  today + YBR->RGB",
    "C": "C  no 422 expand, no convert",
    "D": "D  no 422 expand + YBR->RGB",
}


def main():
    for idx in (1, 22):
        tiles = []
        for key in ("A", "B", "C", "D"):
            path = os.path.join(OUT, "i%02d_%s.png" % (idx, key))
            img = Image.open(path).convert("RGB")
            img.thumbnail((360, 360))
            canvas = Image.new("RGB", (img.width, img.height + 18), (20, 20, 20))
            canvas.paste(img, (0, 18))
            ImageDraw.Draw(canvas).text((4, 4), LABELS[key], fill=(255, 220, 80))
            tiles.append(canvas)
        w = sum(t.width for t in tiles) + 12 * (len(tiles) - 1)
        h = max(t.height for t in tiles)
        sheet = Image.new("RGB", (w, h), (20, 20, 20))
        x = 0
        for tile in tiles:
            sheet.paste(tile, (x, 0))
            x += tile.width + 12
        dest = os.path.join(OUT, "montage_i%02d.png" % idx)
        sheet.save(dest)
        print(dest, sheet.size)


if __name__ == "__main__":
    main()
