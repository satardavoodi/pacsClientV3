"""(a) DICOMDIR presence across cvi42 study folders; (b) build a no-DICOMDIR test folder."""
import io, os, shutil, sys
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

# (a) cheap filesystem check - no DICOM reads, so Dropbox placeholders do not matter
CVI = Path(r"C:\Users\Dr.Alizadeh\Dropbox\Apps\cvi42\mri heart")
folders = [d for d in sorted(CVI.iterdir()) if d.is_dir()]
with_dd = []
for d in folders:
    found = False
    for r, _dirs, fs in os.walk(str(d)):
        if any(f.upper() == "DICOMDIR" for f in fs):
            found = True
            break
    if found:
        with_dd.append(d.name)
print("cvi42 study folders scanned : %d" % len(folders))
print("folders containing a DICOMDIR: %d  %s" % (len(with_dd), with_dd))

# (b) plain per-series test folder, no DICOMDIR
SRC = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test\PT000000")
DST = Path(r"C:\Users\Dr.Alizadeh\Downloads\cvi42_flow_test_no_dicomdir")
WANT = ("flow_ PUL", "flow_ PUL_MAG", "flow_ PUL_P",
        "flow_ AORTA", "flow_ AORTA_MAG", "flow_ AORTA_P")
if DST.exists():
    shutil.rmtree(DST)
DST.mkdir(parents=True)
copied = {}
for r, _dirs, fs in os.walk(str(SRC)):
    for f in fs:
        p = Path(r) / f
        try:
            ds = pydicom.dcmread(str(p), stop_before_pixels=True,
                                 specific_tags=["SeriesDescription", "SeriesNumber",
                                                "InstanceNumber"], force=True)
        except Exception:
            continue
        desc = str(ds.get("SeriesDescription", "") or "")
        if desc not in WANT:
            continue
        num = str(ds.get("SeriesNumber", "0"))
        inst = int(ds.get("InstanceNumber", 0) or 0)
        sub = DST / ("%s_%s" % (num.zfill(3), desc.strip().replace(" ", "_")))
        sub.mkdir(exist_ok=True)
        shutil.copy2(str(p), str(sub / ("IM%04d.dcm" % inst)))
        copied[desc] = copied.get(desc, 0) + 1
print()
print("test folder written to: %s" % DST)
for k in WANT:
    print("   %-18s %d files" % (k, copied.get(k, 0)))
print("   DICOMDIR present: %s" % (DST / "DICOMDIR").exists())
