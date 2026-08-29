"""Phase/magnitude pixel statistics, ours vs the reference.

Answers "is the velocity content itself intact?". Measured on our P series:
raw 0..4094, median 2049, rescaled (slope 2, intercept -4096) to -4096..+4092
centred on zero -- numerically the same behaviour as the working reference
(raw 0..4093, median 2048). The velocity data is NOT damaged.
"""

import io, sys
import numpy as np, pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

OURS = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test\PT000000\ST000000")
REF  = Path(r"C:\Users\Dr.Alizadeh\Dropbox\Apps\cvi42\mri heart\test 31\GHANBARI_SHAHAB_045Y")

def stats(label, path):
    ds = pydicom.dcmread(str(path), force=True)
    a = ds.pixel_array.astype(np.float64)
    sl = float(getattr(ds, "RescaleSlope", 1) or 1)
    ic = float(getattr(ds, "RescaleIntercept", 0) or 0)
    b = a * sl + ic
    print("  %-42s raw[min=%6.0f p1=%6.0f med=%6.0f p99=%6.0f max=%6.0f]  rescaled[min=%8.1f med=%8.1f max=%8.1f]  uniq=%d" % (
        label, a.min(), np.percentile(a,1), np.median(a), np.percentile(a,99), a.max(),
        b.min(), np.median(b), b.max(), len(np.unique(a))))

print("=== OURS (patient 55241, flow_ PUL triplet) ===")
import os
byser = {}
for r,_d,fs in os.walk(str(OURS)):
    for f in fs:
        p = Path(r)/f
        try:
            h = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception:
            continue
        d = str(h.get("SeriesDescription",""))
        if d in ("flow_ PUL","flow_ PUL_MAG","flow_ PUL_P") and d not in byser:
            byser[d] = p
for k in ("flow_ PUL","flow_ PUL_MAG","flow_ PUL_P"):
    if k in byser:
        stats(k, byser[k])

print("=== REFERENCE (works in cvi42) ===")
byser2 = {}
for r,_d,fs in os.walk(str(REF)):
    for f in fs:
        p = Path(r)/f
        if f.upper() == "DICOMDIR":
            continue
        try:
            h = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception:
            continue
        d = str(h.get("SeriesDescription",""))
        if d.endswith("AORTA") or d.endswith("AORTA_MAG") or d.endswith("AORTA_P"):
            if d not in byser2:
                byser2[d] = p
for k in sorted(byser2):
    stats(k, byser2[k])
