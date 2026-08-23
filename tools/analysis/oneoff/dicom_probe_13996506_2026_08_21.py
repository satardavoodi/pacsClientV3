"""One-off: dump the photometric / pixel-layout tags of the failing Breast US study
and compare them against studies that render correctly.

Read-only.  2026-08-21 colour-corruption investigation.
"""
import os
import sys

import pydicom
from pydicom.uid import UID

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
BAD = os.path.join(ROOT, "user_data", "patients", "dicom",
                   "1.2.410.114480.3.2.503247.20260707080007251.1")

TAGS = [
    "SOPClassUID", "Modality", "Manufacturer", "ManufacturerModelName",
    "SamplesPerPixel", "PhotometricInterpretation", "PlanarConfiguration",
    "Rows", "Columns", "NumberOfFrames",
    "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation",
    "RescaleSlope", "RescaleIntercept", "RescaleType",
    "WindowCenter", "WindowWidth", "VOILUTFunction",
    "SmallestImagePixelValue", "LargestImagePixelValue",
    "LossyImageCompression", "LossyImageCompressionMethod",
    "LossyImageCompressionRatio",
]


def describe(path):
    ds = pydicom.dcmread(path, force=True)
    fm = getattr(ds, "file_meta", None)
    ts = getattr(fm, "TransferSyntaxUID", None) if fm else None
    info = {"file": os.path.basename(path)}
    info["TransferSyntaxUID"] = str(ts) if ts else "<absent>"
    if ts:
        try:
            info["TS_name"] = UID(str(ts)).name
            info["TS_compressed"] = bool(UID(str(ts)).is_compressed)
        except Exception:                        # noqa: BLE001
            info["TS_name"] = "?"
    for tag in TAGS:
        if tag in ds:
            info[tag] = str(ds.get(tag))
    info["has_ModalityLUTSequence"] = "ModalityLUTSequence" in ds
    info["has_VOILUTSequence"] = "VOILUTSequence" in ds
    info["has_PaletteColorLUT"] = "RedPaletteColorLookupTableDescriptor" in ds
    info["has_ICCProfile"] = "ICCProfile" in ds
    info["has_OpticalPathSeq"] = "OpticalPathSequence" in ds
    elem = ds["PixelData"] if "PixelData" in ds else None
    info["PixelData_len"] = len(elem.value) if elem is not None else 0
    info["PixelData_encapsulated"] = (
        elem is not None and getattr(elem, "is_undefined_length", False))
    if elem is not None and isinstance(elem.value, (bytes, bytearray)):
        info["PixelData_head"] = elem.value[:16].hex(" ")
    # Ultrasound region calibration is a strong US marker
    info["has_SequenceOfUltrasoundRegions"] = "SequenceOfUltrasoundRegions" in ds
    return ds, info


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else BAD
    files = []
    for dirpath, _dirnames, filenames in os.walk(target):
        for name in sorted(filenames):
            files.append(os.path.join(dirpath, name))
    print("== %s ==" % target.replace(ROOT, "."))
    print("   %d file(s)" % len(files))
    if not files:
        return
    for path in files[:2]:
        ds, info = describe(path)
        print()
        for key, value in info.items():
            print("   %-34s %s" % (key, value))
        # try the actual decode pydicom would do
        print("   -- decode attempt --")
        try:
            arr = ds.pixel_array
            print("   %-34s %s %s  min=%s max=%s" % (
                "pixel_array", arr.shape, arr.dtype, arr.min(), arr.max()))
        except Exception as exc:                 # noqa: BLE001
            print("   %-34s FAILED: %r" % ("pixel_array", exc))


if __name__ == "__main__":
    main()
