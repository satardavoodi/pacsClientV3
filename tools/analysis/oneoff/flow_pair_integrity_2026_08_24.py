"""Magnitude/phase pair integrity + SOP-UID and VR=UN census over our export.

For each flow location, checks that MAG and P share geometry, share trigger
times and have equal instance counts -- the preconditions any flow package
needs to pair them. Measured: all true for PUL, AORTA and MITRAL; 1570 files
with 1570 distinct SOPInstanceUIDs and zero duplicates; the only VR=UN element
anywhere in the flow files is (0051,1014), in all 240 of them.
"""

import io, os, sys, collections
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

OURS = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test\PT000000")

series = collections.OrderedDict()
sop = collections.Counter()
un_census = collections.Counter()
for r,_d,fs in os.walk(str(OURS)):
    for f in fs:
        p = Path(r)/f
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        except Exception:
            continue
        sop[str(ds.get("SOPInstanceUID"))] += 1
        desc = str(ds.get("SeriesDescription","") or "")
        if "flow" in desc.lower():
            series.setdefault(desc, []).append(ds)
            for e in ds:
                if e.VR == "UN":
                    un_census[str(e.tag)] += 1

print("SOPInstanceUIDs: %d files, %d distinct, duplicates=%d" % (
    sum(sop.values()), len(sop), sum(1 for v in sop.values() if v > 1)))
print("VR=UN private elements seen in flow files:", dict(un_census))
print()

def key(ds):
    return (tuple(round(float(x),4) for x in (ds.get("ImagePositionPatient") or [])),
            tuple(round(float(x),4) for x in (ds.get("ImageOrientationPatient") or [])),
            tuple(float(x) for x in (ds.get("PixelSpacing") or [])),
            int(ds.get("Rows",0)), int(ds.get("Columns",0)))

groups = [("flow_ PUL","flow_ PUL_MAG","flow_ PUL_P"),
          ("flow_ AORTA","flow_ AORTA_MAG","flow_ AORTA_P"),
          ("flow_ MITRAL","flow_ MITRAL_MAG","flow_ MITRAL_P")]
for grp in groups:
    print("=" * 92)
    print("GROUP", grp)
    for name in grp:
        items = series.get(name)
        if not items:
            print("   %-24s MISSING FROM EXPORT" % name); continue
        items.sort(key=lambda d: int(d.get("InstanceNumber", 0) or 0))
        tts = [float(d.get("TriggerTime", -1)) for d in items]
        geo = {key(d) for d in items}
        print("   %-24s n=%-3d  geo_variants=%d  TT distinct=%d  first=%.1f last=%.1f" % (
            name, len(items), len(geo), len(set(tts)), tts[0], tts[-1]))
        print("        SeriesNumber=%s  SeriesTime=%s  AcqNo=%s  EchoNo=%s" % (
            items[0].get("SeriesNumber"), items[0].get("SeriesTime"),
            items[0].get("AcquisitionNumber"), items[0].get("EchoNumbers")))
    # MAG vs P alignment
    m, p = series.get(grp[1]), series.get(grp[2])
    if m and p:
        m = sorted(m, key=lambda d: int(d.get("InstanceNumber",0) or 0))
        p = sorted(p, key=lambda d: int(d.get("InstanceNumber",0) or 0))
        same_geo = key(m[0]) == key(p[0])
        tt_m = [float(d.get("TriggerTime",-1)) for d in m]
        tt_p = [float(d.get("TriggerTime",-1)) for d in p]
        print("   MAG/P: same geometry=%s   same trigger times=%s   n equal=%s" % (
            same_geo, tt_m == tt_p, len(m) == len(p)))
