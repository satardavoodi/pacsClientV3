"""Per-series flow summary across ALL instances of patient 55241.

Study 1.3.12.2.1107.5.2.46.174759.30000026082304314150700000025 (SIEMENS Amira,
syngo MR E11). Prints, for each flow series, the M/MAG/P ImageType, SequenceName
(which carries the VENC as *fl2d1_v150in), UID uniqueness, InstanceNumber range,
transfer syntax, TriggerTime progression, rescale, bit depth and the byte length
of both Siemens CSA blocks.

NOTE the flow series are 45-56, not 44-49: 45/46/47 PUL, 48/49/50 AORTA,
51/52/53 MITRAL, 54/55/56 MID HEART. Series 44 is Angio3D_cor_post.
"""

import io, sys, collections
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

BASE = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026082304314150700000025")

def g(ds, kw, default=None):
    return ds[kw].value if kw in ds else default

for sn in sorted(int(p.name) for p in BASE.iterdir() if p.is_dir() and p.name.isdigit()):
    if sn < 44 or sn > 62:
        continue
    d = BASE / str(sn)
    files = sorted(d.glob("*.dcm"))
    if not files:
        continue
    first = pydicom.dcmread(str(files[0]), stop_before_pixels=True, force=True)
    desc = g(first, "SeriesDescription", "")
    if "flow" not in str(desc).lower():
        print("%3d  %-32s  (%d files)  [skipped - not flow]" % (sn, desc, len(files)))
        continue
    tt, uids, inums, itypes, suids, ts, csa1, csa2 = [], set(), [], collections.Counter(), set(), collections.Counter(), [], []
    for f in files:
        ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
        uids.add(str(g(ds, "SOPInstanceUID")))
        suids.add(str(g(ds, "SeriesInstanceUID")))
        inums.append(g(ds, "InstanceNumber"))
        v = g(ds, "TriggerTime")
        if v is not None:
            tt.append(float(v))
        itypes[str(list(g(ds, "ImageType", [])))] += 1
        ts[str(getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None))] += 1
        e = ds.get((0x0029, 0x1010)); csa1.append(len(e.value) if e is not None and e.value else 0)
        e = ds.get((0x0029, 0x1020)); csa2.append(len(e.value) if e is not None and e.value else 0)
    tt.sort()
    print("=" * 100)
    print("SERIES %-3d  %-28s  files=%d" % (sn, desc, len(files)))
    print("   ProtocolName    : %s" % g(first, "ProtocolName"))
    print("   SequenceName    : %s" % g(first, "SequenceName"))
    print("   SeriesNumber    : %s" % g(first, "SeriesNumber"))
    print("   SeriesUID       : %s  (distinct=%d)" % (list(suids)[0], len(suids)))
    print("   SOPInstanceUIDs : distinct=%d" % len(uids))
    print("   InstanceNumbers : %s..%s  n=%d" % (min(inums), max(inums), len(inums)))
    print("   ImageType       : %s" % dict(itypes))
    print("   TransferSyntax  : %s" % dict(ts))
    print("   TriggerTime     : n=%d  %.1f .. %.1f  step~%.1f" % (len(tt), tt[0], tt[-1], (tt[-1]-tt[0])/max(1,len(tt)-1)))
    print("   Rescale         : slope=%s intercept=%s type=%s" % (g(first,"RescaleSlope"), g(first,"RescaleIntercept"), g(first,"RescaleType")))
    print("   Bits            : alloc=%s stored=%s high=%s pixrep=%s" % (g(first,"BitsAllocated"), g(first,"BitsStored"), g(first,"HighBit"), g(first,"PixelRepresentation")))
    print("   CSA image bytes : min=%d max=%d   CSA series bytes: min=%d max=%d" % (min(csa1), max(csa1), min(csa2), max(csa2)))
    print("   CardiacNumImgs  : %s   NominalInterval: %s" % (g(first,"CardiacNumberOfImages"), g(first,"NominalInterval")))
