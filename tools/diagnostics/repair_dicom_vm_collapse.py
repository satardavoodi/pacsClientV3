"""Repair VM-collapsed DICOM string elements in an exported folder.

Context: docs/reports/DICOM_EXPORT_VM_COLLAPSE_LIMBUS_RT_BLACK_IMAGES_2026-07-14.md

The AI-PACS server serialises multi-valued STRING elements as a Python list repr, so
they arrive with VM collapsed to 1 and (for VR CS) characters that are ILLEGAL per PS3.5:

    (0008,0008) Image Type  ->  "['ORIGINAL', 'PRIMARY', 'AXIAL', 'CT_SOM5 SPI']"   (VM 1)
    correct                 ->   ORIGINAL\\PRIMARY\\AXIAL\\CT_SOM5 SPI              (VM 4)

Image Type is Type 1 (mandatory) in the CT Image IOD. Tolerant readers (our viewer, Limbus)
accept it; strict readers (radiotherapy planning systems) do not.

This tool restores the true multi-valued form, and empties the fabricated
(0008,0050) Accession Number "0" that the DICOMDIR/offline export writes into instances
(Accession Number is Type 2 — an unknown accession must stay EMPTY).

It NEVER touches pixel data, UIDs, geometry, windowing, rescale or the transfer syntax.
Dry-run by default; --apply backs each file up to <file>.bak before rewriting.

Usage:
    python tools/diagnostics/repair_dicom_vm_collapse.py "<folder>"
    python tools/diagnostics/repair_dicom_vm_collapse.py "<folder>" --apply
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import sys

try:
    import pydicom
except ImportError:  # pragma: no cover
    print("pydicom is required: pip install pydicom")
    raise SystemExit(2)

LIST_REPR = re.compile(r"^\[.*\]$")

# VRs whose values are text. A list-repr can only be a corruption for these.
_STRING_VRS = {"AE", "AS", "CS", "DA", "DT", "LO", "LT", "PN", "SH", "ST", "TM", "UC", "UI", "UR", "UT"}


def repair_dataset(ds) -> list[str]:
    """Return the list of element names repaired (mutates ``ds``)."""
    fixed: list[str] = []

    for elem in ds:
        if elem.tag == (0x7FE0, 0x0010):  # never look at pixel data
            continue
        if elem.VR not in _STRING_VRS:
            continue
        value = elem.value
        if not isinstance(value, str) or not LIST_REPR.match(value.strip()):
            continue
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(parsed, list) and parsed and all(isinstance(x, str) for x in parsed):
            elem.value = parsed  # pydicom re-encodes as backslash-separated, correct VM
            fixed.append(f"{elem.tag} {elem.name}")

    # Accession Number is Type 2: the export fabricates "0" when the source is empty.
    if "AccessionNumber" in ds and str(ds.AccessionNumber).strip() == "0":
        ds.AccessionNumber = ""
        fixed.append("(0008,0050) Accession Number")

    return fixed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="exported DICOM folder to inspect / repair")
    ap.add_argument("--apply", action="store_true", help="write the repair (default: report only)")
    ap.add_argument("--no-backup", action="store_true", help="skip the .bak copy (with --apply)")
    args = ap.parse_args(argv)

    root = args.folder
    if not os.path.isdir(root):
        print(f"not a folder: {root}")
        return 2

    scanned = clean = repaired = failed = 0
    per_element: dict[str, int] = {}

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if name.endswith(".bak"):
                continue
            try:
                ds = pydicom.dcmread(path, force=True)
            except Exception:
                continue
            if not getattr(ds, "SOPClassUID", None) and "DirectoryRecordSequence" not in ds:
                continue

            scanned += 1
            fixed = repair_dataset(ds)
            if not fixed:
                clean += 1
                continue
            for f in fixed:
                per_element[f] = per_element.get(f, 0) + 1

            if not args.apply:
                repaired += 1
                continue

            try:
                if not args.no_backup:
                    shutil.copy2(path, path + ".bak")
                ds.save_as(path, write_like_original=False)
                repaired += 1
            except Exception as exc:
                failed += 1
                print(f"  FAILED {path}: {exc}")

    mode = "REPAIRED" if args.apply else "WOULD REPAIR (dry run — pass --apply to write)"
    print(f"\nfolder   : {root}")
    print(f"scanned  : {scanned} DICOM file(s)")
    print(f"clean    : {clean}")
    print(f"{mode}: {repaired}")
    if failed:
        print(f"failed   : {failed}")
    if per_element:
        print("\nelements affected:")
        for elem, n in sorted(per_element.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d}  {elem}")
    else:
        print("\nno VM-collapsed elements found — this export is already conformant.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
