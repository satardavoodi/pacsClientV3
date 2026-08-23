"""One-off: verify the YBR fix through the REAL decode path (decode_service worker).

Runs `_decode_worker` over every instance of the failing study and reports the
row-to-row correlation of the result (a real image correlates strongly; scrambled
samples do not).  Also re-runs with the kill switches OFF to show the pre-fix
behaviour on the same code.
"""
import os
import sys

import numpy as np
import pydicom

sys.path.insert(0, r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
STUDY = os.path.join(ROOT, "user_data", "patients", "dicom",
                     "1.2.410.114480.3.2.503247.20260707080007251.1")
OUT = os.path.join(ROOT, "user_data", "_ybr_repro")


def corr(img):
    g = np.asarray(img).astype(np.float32)
    if g.ndim == 3:
        g = g.mean(axis=2)
    a, b = g[:-1].ravel(), g[1:].ravel()
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def run(label):
    from modules.viewer.fast.decode_service import _decode_worker
    files = sorted(os.path.join(dp, f)
                   for dp, _dn, fn in os.walk(STUDY) for f in fn)
    scores = []
    for path in files:
        hdr = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        arr = _decode_worker(
            path,
            int(hdr.Rows), int(hdr.Columns), 1.0, 0.0,
            str(hdr.PhotometricInterpretation),
            int(hdr.SamplesPerPixel),
        )
        scores.append((corr(arr), os.path.basename(path), arr.shape, str(arr.dtype)))
    good = [s for s, *_ in scores if s > 0.5]
    print("%-14s instances=%d  corr>0.5: %d/%d   min=%.3f  median=%.3f  max=%.3f"
          % (label, len(scores), len(good), len(scores),
             min(s for s, *_ in scores),
             float(np.median([s for s, *_ in scores])),
             max(s for s, *_ in scores)))
    worst = sorted(scores)[:3]
    for s, name, shape, dtype in worst:
        print("      worst %.3f  %s %s %s" % (s, name, shape, dtype))
    return scores


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "on"
    if mode == "off":
        os.environ["AIPACS_DICOM_YBR422_FIX"] = "0"
        os.environ["AIPACS_DICOM_YBR_TO_RGB"] = "0"
    scores = run("fix=%s" % mode)

    # Save the first corrected frame for eyeballing.
    if mode == "on":
        from PIL import Image
        from modules.viewer.fast.decode_service import _decode_worker
        files = sorted(os.path.join(dp, f)
                       for dp, _dn, fn in os.walk(STUDY) for f in fn)
        hdr = pydicom.dcmread(files[22], stop_before_pixels=True, force=True)
        arr = _decode_worker(files[22], int(hdr.Rows), int(hdr.Columns), 1.0, 0.0,
                             str(hdr.PhotometricInterpretation),
                             int(hdr.SamplesPerPixel))
        os.makedirs(OUT, exist_ok=True)
        Image.fromarray(np.ascontiguousarray(arr), "RGB").save(
            os.path.join(OUT, "verified_i22_decode_service.png"))
        print("   wrote", os.path.join(OUT, "verified_i22_decode_service.png"))
    return scores


if __name__ == "__main__":
    main()
