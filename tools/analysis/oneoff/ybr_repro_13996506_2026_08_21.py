"""One-off: reproduce the AI-PACS colour path for the ALPINION US Breast study.

Writes three PNGs per probed instance into user_data/../_ybr_repro/:
  *_current.png  - what the FAST viewer paints today (raw samples as RGB)
  *_fixed.png    - YBR -> RGB via pydicom convert_color_space
  *_delta.txt    - per-channel stats so the difference is measurable

Read-only with respect to the study.  2026-08-21 investigation.
"""
import os

import numpy as np
import pydicom
from PIL import Image

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
STUDY = os.path.join(ROOT, "user_data", "patients", "dicom",
                     "1.2.410.114480.3.2.503247.20260707080007251.1")
OUT = os.path.join(ROOT, "user_data", "_ybr_repro")


def main():
    os.makedirs(OUT, exist_ok=True)
    files = []
    for dirpath, _dn, filenames in os.walk(STUDY):
        for name in sorted(filenames):
            files.append(os.path.join(dirpath, name))

    photo_counts = {}
    for path in files:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        key = (str(getattr(ds, "PhotometricInterpretation", "?")),
               int(getattr(ds, "SamplesPerPixel", 0) or 0),
               str(getattr(ds, "SOPClassUID", "?")),
               int(getattr(ds, "PlanarConfiguration", -1) or 0))
        photo_counts[key] = photo_counts.get(key, 0) + 1
    print("== photometric distribution across %d instances ==" % len(files))
    for key, count in sorted(photo_counts.items()):
        print("   %-14s spp=%d planar=%d n=%3d  sop=%s" %
              (key[0], key[1], key[3], count, key[2]))

    print()
    from pydicom.pixel_data_handlers.util import convert_color_space
    for idx in (0, 1, len(files) // 2):
        path = files[idx]
        ds = pydicom.dcmread(path, force=True)
        photometric = str(ds.PhotometricInterpretation)
        arr = np.asarray(ds.pixel_array)
        base = "%02d_%s" % (idx, photometric.replace(" ", "_"))

        cur = np.ascontiguousarray(arr.astype(np.uint8))
        Image.fromarray(cur, "RGB").save(os.path.join(OUT, base + "_current.png"))

        fixed = convert_color_space(arr, photometric, "RGB")
        fixed = np.ascontiguousarray(np.clip(fixed, 0, 255).astype(np.uint8))
        Image.fromarray(fixed, "RGB").save(os.path.join(OUT, base + "_fixed.png"))

        diff = np.abs(cur.astype(np.int16) - fixed.astype(np.int16))
        print("   %s  shape=%s" % (base, arr.shape))
        print("      current  ch-means R=%6.1f G=%6.1f B=%6.1f" %
              tuple(cur[..., c].mean() for c in range(3)))
        print("      fixed    ch-means R=%6.1f G=%6.1f B=%6.1f" %
              tuple(fixed[..., c].mean() for c in range(3)))
        print("      abs-diff mean=%.1f  max=%d  pct>16=%.1f%%" %
              (diff.mean(), diff.max(),
               100.0 * float((diff > 16).sum()) / diff.size))
    print()
    print("PNGs written to", OUT)


if __name__ == "__main__":
    main()
