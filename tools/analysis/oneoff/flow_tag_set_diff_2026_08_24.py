"""Full tag-set diff, both directions, between our flow P/MAG files and the
reference cvi42 dataset.

Read the output with the scanner-generation caveat in mind: the ~101 tags
"present in reference, absent from ours" are almost entirely the XA20-era
(0021,xxxx) SIEMENS MR SDS/SDI/SDR private blocks, which an E11 scanner does
not emit at all. The only genuine encoding anomaly on our side is (0051,1014)
carrying VR=UN.
"""

import io, os, sys, collections
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

OURS = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test\PT000000")
REF  = Path(r"C:\Users\Dr.Alizadeh\Dropbox\Apps\cvi42\mri heart\test 31\GHANBARI_SHAHAB_045Y")

def walk(root):
    for r, _d, fs in os.walk(str(root)):
        for n in fs:
            if n.upper() == "DICOMDIR":
                continue
            yield Path(r) / n

def find_one(root, want_imagetype):
    for p in walk(root):
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception:
            continue
        it = [str(x) for x in (ds.get("ImageType", []) or [])]
        desc = str(ds.get("SeriesDescription","") or "")
        if want_imagetype in it and "flow" in desc.lower():
            return p, ds
    return None, None

def tagmap(ds):
    d = {}
    for e in ds:
        d[e.tag] = e
    return d

for kind in ("P", "MAG"):
    po, dso = find_one(OURS, kind)
    pr, dsr = find_one(REF, kind)
    if dso is None or dsr is None:
        print("could not find %s in one of the trees" % kind); continue
    print("#" * 100)
    print("### %s-image comparison" % kind)
    print("  ours: %s   [%s]" % (po.name, dso.get("SeriesDescription")))
    print("  ref : %s   [%s]" % (pr.name, dsr.get("SeriesDescription")))
    to, tr = tagmap(dso), tagmap(dsr)
    only_ref = sorted(set(tr) - set(to))
    only_our = sorted(set(to) - set(tr))
    print("\n  --- present in REFERENCE, ABSENT from ours (%d) ---" % len(only_ref))
    for t in only_ref:
        e = tr[t]
        v = e.value
        s = ("<%d bytes>" % len(v)) if isinstance(v,(bytes,bytearray)) else str(v)
        print("    %s %-4s %-44s %s" % (t, e.VR, (e.name or "")[:44], s[:60]))
    print("\n  --- present in OURS, absent from reference (%d) ---" % len(only_our))
    for t in only_our:
        e = to[t]
        v = e.value
        s = ("<%d bytes>" % len(v)) if isinstance(v,(bytes,bytearray)) else str(v)
        print("    %s %-4s %-44s %s" % (t, e.VR, (e.name or "")[:44], s[:60]))
