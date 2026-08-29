"""Validate the DICOMDIR our CD export writes.

Checks record counts, that every IMAGE record's ReferencedFileID resolves to a
real file, and -- the point of the script -- WHICH KEYS the SERIES and IMAGE
records actually carry.

Measured: SERIES records carry only Modality, SeriesInstanceUID, SeriesNumber.
There is no SeriesDescription and no ProtocolName, because
modules/dicom_media/dicomdir.py builds the set with pydicom's FileSet and
pydicom's DEFAULT SERIES recorder emits exactly those three elements. DCMTK's
dcmmkdir -- what conventional PACS use -- includes SeriesDescription.
"""

import io, os, sys, collections
import pydicom
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings; warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\Dr.Alizadeh\Downloads\cardiac mri  test")
dd = pydicom.dcmread(str(ROOT / "DICOMDIR"), force=True)
fm = dd.file_meta
print("DICOMDIR MediaStorageSOPClassUID:", getattr(fm, "MediaStorageSOPClassUID", None))
print("DICOMDIR TransferSyntax        :", getattr(fm, "TransferSyntaxUID", None))
print("DICOMDIR Implementation        :", getattr(fm,"ImplementationClassUID",None), "/", getattr(fm,"ImplementationVersionName",None))
print("FileSetID                      :", dd.get("FileSetID"))

recs = dd.DirectoryRecordSequence
kinds = collections.Counter(str(r.DirectoryRecordType) for r in recs)
print("records:", dict(kinds), " total:", len(recs))

missing, present = [], 0
img_by_series = collections.Counter()
cur_series = None
series_meta = {}
for r in recs:
    t = str(r.DirectoryRecordType)
    if t == "SERIES":
        cur_series = str(r.get("SeriesInstanceUID"))
        series_meta[cur_series] = (r.get("SeriesNumber"), r.get("Modality"),
                                   [k for k in ("SeriesDescription","ProtocolName") if k in r])
    elif t == "IMAGE":
        img_by_series[cur_series] += 1
        fid = r.get("ReferencedFileID")
        if fid is None:
            missing.append("<no ReferencedFileID>"); continue
        parts = list(fid) if not isinstance(fid, str) else [fid]
        p = ROOT.joinpath(*[str(x) for x in parts])
        if p.exists():
            present += 1
        else:
            missing.append(str(p))
print("IMAGE records resolving to a real file: %d ; missing: %d" % (present, len(missing)))
for m in missing[:10]:
    print("   MISSING:", m)

on_disk = sum(1 for r,_d,fs in os.walk(str(ROOT/"PT000000")) for f in fs)
print("files on disk under PT000000:", on_disk)
print("series records:", len(series_meta))
print("\nSERIES records - fields carried:")
for i,(uid,(num,mod,extra)) in enumerate(list(series_meta.items())[:6]):
    print("   #%d SeriesNumber=%s Modality=%s extra_keys=%s" % (i, num, mod, extra))
# what keys does a SERIES record actually have?
for r in recs:
    if str(r.DirectoryRecordType) == "SERIES":
        print("\nexample SERIES record keys:", [e.keyword or str(e.tag) for e in r])
        break
for r in recs:
    if str(r.DirectoryRecordType) == "IMAGE":
        print("example IMAGE  record keys:", [e.keyword or str(e.tag) for e in r])
        break
