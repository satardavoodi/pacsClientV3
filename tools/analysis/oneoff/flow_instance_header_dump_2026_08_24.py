"""Dump the flow-relevant DICOM header of one (or n) instances of a series folder.

Usage: python <this> <series_folder> [n]
Prints file-meta (transfer syntax, implementation class/version -- ours reads
PACS_SERVER_1.0 with the pydicom UID root, i.e. the server re-encodes rather
than storing the scanner bytes verbatim), the standard MR/cardiac elements, and
every private / flow-specific element.
"""

import io, sys
import pydicom
from pydicom.tag import Tag
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

d = Path(sys.argv[1])
files = sorted(d.glob("*.dcm"))
n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
for f in files[:n]:
    ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
    print("=" * 78)
    print(f.name)
    fm = getattr(ds, "file_meta", None)
    if fm:
        print("  TransferSyntax  :", getattr(fm, "TransferSyntaxUID", None), "|", getattr(getattr(fm,'TransferSyntaxUID',None),'name','?'))
        print("  MediaStorageSOP :", getattr(fm, "MediaStorageSOPClassUID", None))
        print("  ImplClassUID    :", getattr(fm, "ImplementationClassUID", None))
        print("  ImplVersionName :", getattr(fm, "ImplementationVersionName", None))
        print("  SourceAE        :", getattr(fm, "SourceApplicationEntityTitle", None))
    for kw in ("SOPClassUID","SOPInstanceUID","Modality","Manufacturer","ManufacturerModelName",
               "SoftwareVersions","ImageType","SeriesDescription","ProtocolName","SequenceName",
               "ScanningSequence","SequenceVariant","ScanOptions","MRAcquisitionType",
               "SeriesNumber","SeriesInstanceUID","AcquisitionNumber","InstanceNumber",
               "TemporalPositionIdentifier","NumberOfTemporalPositions","TriggerTime",
               "NominalInterval","HeartRate","CardiacNumberOfImages","RepetitionTime","EchoTime",
               "FlipAngle","EchoNumbers","AcquisitionTime","ContentTime",
               "RescaleIntercept","RescaleSlope","RescaleType","WindowCenter","WindowWidth",
               "BitsAllocated","BitsStored","HighBit","PixelRepresentation","SamplesPerPixel",
               "PhotometricInterpretation","Rows","Columns","PixelSpacing","SliceThickness",
               "ImagePositionPatient","ImageOrientationPatient","FrameOfReferenceUID",
               "StudyInstanceUID","LargestImagePixelValue","SmallestImagePixelValue"):
        if kw in ds:
            v = ds.data_element(kw).value
            s = str(v)
            print("  %-24s: %s" % (kw, s[:150]))
    print("  -- private / flow-specific --")
    for elem in ds:
        t = elem.tag
        if t.is_private or (0x0018 <= t.group <= 0x0018 and 0x9000 <= t.element <= 0x9300) \
           or t.group in (0x0021, 0x0029, 0x0019, 0x0051) or (t.group == 0x0040 and t.element == 0x9096):
            val = elem.value
            if isinstance(val, bytes):
                shown = "<%d bytes> %r" % (len(val), val[:48])
            else:
                shown = str(val)[:160]
            print("   %s %-34s %s = %s" % (t, (elem.name or "")[:34], elem.VR, shown))
