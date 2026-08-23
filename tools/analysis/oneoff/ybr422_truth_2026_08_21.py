"""One-off: prove what pydicom does with the mislabelled YBR_FULL_422 US frames.

Compares four interpretations of the SAME instance and writes a PNG for each:
  A  ds.pixel_array as-is, painted as RGB          <- what AI-PACS shows today
  B  ds.pixel_array, convert_color_space -> RGB    <- naive "add YBR conversion"
  C  raw PixelData reshaped (R,C,3), painted RGB   <- no 422 expansion, no convert
  D  raw PixelData reshaped (R,C,3), YBR -> RGB    <- proposed correct rendering

2026-08-21 investigation.  Read-only with respect to the study.
"""
import os

import numpy as np
import pydicom
from PIL import Image
from pydicom.pixel_data_handlers.util import convert_color_space

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
STUDY = os.path.join(ROOT, "user_data", "patients", "dicom",
                     "1.2.410.114480.3.2.503247.20260707080007251.1")
OUT = os.path.join(ROOT, "user_data", "_ybr_repro")


def stats(name, a):
    print("      %-34s shape=%-18s means R=%6.1f G=%6.1f B=%6.1f" % (
        name, str(a.shape),
        a[..., 0].mean(), a[..., 1].mean(), a[..., 2].mean()))


def main():
    print("pydicom", pydicom.__version__)
    os.makedirs(OUT, exist_ok=True)
    files = sorted(
        os.path.join(dp, f)
        for dp, _dn, fn in os.walk(STUDY) for f in fn
    )
    for idx in (1, 22):
        path = files[idx]
        ds = pydicom.dcmread(path, force=True)
        photometric = str(ds.PhotometricInterpretation)
        rows, cols = int(ds.Rows), int(ds.Columns)
        spp = int(ds.SamplesPerPixel)
        raw = ds["PixelData"].value
        print()
        print("   [%02d] %s  %dx%d spp=%d  raw=%d  rows*cols*spp=%d" % (
            idx, photometric, rows, cols, spp, len(raw), rows * cols * spp))

        a = np.asarray(ds.pixel_array).astype(np.uint8)
        stats("A pixel_array as-RGB", a)
        b = np.clip(convert_color_space(a, photometric, "RGB"), 0, 255).astype(np.uint8)
        stats("B pixel_array YBR->RGB", b)

        c = np.frombuffer(raw[:rows * cols * spp], dtype=np.uint8).reshape(rows, cols, spp)
        stats("C raw reshape as-RGB", c)
        d = np.clip(convert_color_space(c, "YBR_FULL", "RGB"), 0, 255).astype(np.uint8)
        stats("D raw reshape YBR->RGB", d)

        # Row-to-row correlation is a blunt but effective "is this an image or
        # is this noise" probe: a real anatomical frame correlates strongly
        # between adjacent rows; scrambled samples do not.
        for name, img in (("A", a), ("B", b), ("C", c), ("D", d)):
            g = img.astype(np.float32).mean(axis=2)
            r0, r1 = g[:-1].ravel(), g[1:].ravel()
            corr = float(np.corrcoef(r0, r1)[0, 1])
            print("      %s row-to-row correlation = %.4f" % (name, corr))
            Image.fromarray(np.ascontiguousarray(img), "RGB").save(
                os.path.join(OUT, "i%02d_%s.png" % (idx, name)))
    print()
    print("PNGs in", OUT)


if __name__ == "__main__":
    main()
