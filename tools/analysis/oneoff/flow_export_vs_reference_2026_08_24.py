"""Side-by-side flow-series comparison: our CD export vs a known-good cvi42 dataset.

CAVEAT, and it matters: the reference (GHANBARI_SHAHAB_045Y) is a DIFFERENT
patient on a DIFFERENT scanner generation -- MAGNETOM Altea / syngo MR XA20 --
and is cvi42's own rewritten copy (ImplementationVersionName=CVI42_DCMTK_360)
with the CSA blocks already stripped. It proves cvi42 does flow; it is NOT a
control for what our export is missing.
"""

import io, os, re, struct, sys, collections
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

OURS = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test\PT000000")
REF  = Path(r"C:\Users\Dr.Alizadeh\Dropbox\Apps\cvi42\mri heart\test 31\GHANBARI_SHAHAB_045Y")

def walk(root):
    for r, _d, fs in os.walk(str(root)):
        for n in fs:
            p = Path(r) / n
            if p.name.upper() == "DICOMDIR":
                continue
            yield p

def head(p):
    try:
        return pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
    except Exception:
        return None

def summarise(root, label):
    print("#" * 100)
    print("### %s   %s" % (label, root))
    by_series = collections.OrderedDict()
    for p in walk(root):
        ds = head(p)
        if ds is None or "SeriesInstanceUID" not in ds:
            continue
        key = str(ds.SeriesInstanceUID)
        by_series.setdefault(key, []).append((p, ds))
    print("total series: %d" % len(by_series))
    flow = []
    for key, items in by_series.items():
        p, ds = items[0]
        desc = str(ds.get("SeriesDescription", "") or "")
        seq = str(ds.get("SequenceName", "") or "")
        it = [str(x) for x in (ds.get("ImageType", []) or [])]
        is_flow = ("flow" in desc.lower() or "_v" in seq or "P" in it or "MAG" in it
                   or re.search(r"fl.*_v\d", seq or "", re.I))
        if is_flow:
            flow.append((key, items))
    print("flow-ish series: %d" % len(flow))
    out = []
    for key, items in flow:
        p, ds = items[0]
        out.append((str(ds.get("SeriesNumber","")), str(ds.get("SeriesDescription","")), key, items))
    out.sort(key=lambda r: int(r[0]) if str(r[0]).isdigit() else 0)
    for sn, desc, key, items in out:
        p, ds = items[0]
        print("-" * 96)
        print("  Series %-5s %-30s  n=%-4d" % (sn, desc[:30], len(items)))
        for kw in ("Manufacturer","ManufacturerModelName","SoftwareVersions","ImageType","ProtocolName",
                   "SequenceName","RescaleSlope","RescaleIntercept","RescaleType","BitsStored",
                   "CardiacNumberOfImages","NominalInterval","TriggerTime","AcquisitionNumber",
                   "SOPClassUID","NumberOfFrames"):
            if kw in ds:
                print("      %-22s %s" % (kw, str(ds[kw].value)[:90]))
        fm = getattr(ds, "file_meta", None)
        if fm:
            print("      %-22s %s" % ("TransferSyntax", getattr(fm, "TransferSyntaxUID", None)))
            print("      %-22s %s / %s" % ("Implementation", getattr(fm,"ImplementationClassUID",None), getattr(fm,"ImplementationVersionName",None)))
        for tag, name in (((0x0029,0x1010),"CSA-image"), ((0x0029,0x1020),"CSA-series"),
                          ((0x0019,0x100b),"0019,100b"), ((0x0051,0x1011),"0051,1011")):
            el = ds.get(tag)
            v = el.value if el is not None else None
            n = len(v) if isinstance(v, (bytes, bytearray)) else (len(str(v)) if v is not None else 0)
            print("      %-22s %s (%s bytes) VR=%s" % (name, "present" if el is not None else "ABSENT", n, el.VR if el is not None else "-"))
        print("      top-level elements: %d   private elements: %d" % (len(list(ds)), sum(1 for e in ds if e.tag.is_private)))
    return out

a = summarise(OURS, "OUR PACS EXPORT")
b = summarise(REF, "REFERENCE (works in cvi42)")
