"""Report which locally-stored studies hold COMPRESSED pixel data.  READ-ONLY.

Why this exists
---------------
AI-PACS normalizes compressed DICOM to Explicit VR Little Endian at FOLDER-IMPORT
time only (``import_preview_dialog._decompress_file_to_destination``).  The
network download path writes server bytes verbatim — its ``is_compressed`` flag
is a gzip TRANSPORT envelope, not a DICOM transfer syntax — so once the server
starts sending compressed pixel data, studies land in local storage still
encapsulated.

Download resume keys on file presence + a >=128-byte size check, so such a study
is treated as complete and is never re-fetched.  This tool tells you the blast
radius before you decide what to do about it.

It NEVER writes, moves or deletes anything.

Usage
-----
    python tools/diagnostics/scan_compressed_studies.py
    python tools/diagnostics/scan_compressed_studies.py --root <dir> --json out.json
    python tools/diagnostics/scan_compressed_studies.py --sample 3   # files/series to probe

Exit code is 0 always (a report, not a gate).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("WINDIR", r"C:\Windows")
os.environ.setdefault("SystemRoot", r"C:\Windows")

UNCOMPRESSED = {
    "1.2.840.10008.1.2",      # Implicit VR LE
    "1.2.840.10008.1.2.1",    # Explicit VR LE
    "1.2.840.10008.1.2.1.99",  # Deflated Explicit VR LE
    "1.2.840.10008.1.2.2",    # Explicit VR BE
}


def _default_root() -> Path:
    try:
        from PacsClient.utils.data_paths import DICOM_IMAGES_DIR
        return Path(DICOM_IMAGES_DIR)
    except Exception:
        return PROJECT_ROOT / "user_data" / "patients" / "dicom"


def _ts_of(path: Path):
    """Transfer syntax UID of a file, or None when unreadable/not DICOM."""
    import pydicom
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except Exception:
        return None
    ts = getattr(getattr(ds, "file_meta", None), "TransferSyntaxUID", None)
    return str(ts) if ts else None


def _ts_name(uid: str) -> str:
    try:
        from pydicom.uid import UID
        return UID(uid).name
    except Exception:
        return uid


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="patient DICOM root (default: app storage)")
    ap.add_argument("--sample", type=int, default=2,
                    help="files probed per series (default 2; 0 = every file)")
    ap.add_argument("--json", default=None, help="also write the full report as JSON")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else _default_root()
    print(f"scanning: {root}")
    if not root.exists():
        print("  root does not exist — nothing to scan.")
        return 0

    per_study: dict[str, Counter] = defaultdict(Counter)
    per_study_series: dict[str, set] = defaultdict(set)
    compressed_series: dict[str, set] = defaultdict(set)
    totals = Counter()
    unreadable = 0
    scanned = 0

    for study_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        study_uid = study_dir.name
        for series_dir in sorted(p for p in study_dir.iterdir() if p.is_dir()):
            files = sorted(series_dir.glob("*.dcm"))
            if not files:
                continue
            per_study_series[study_uid].add(series_dir.name)
            probe = files if args.sample <= 0 else files[: args.sample]
            for f in probe:
                ts = _ts_of(f)
                scanned += 1
                if ts is None:
                    unreadable += 1
                    continue
                totals[ts] += 1
                per_study[study_uid][ts] += 1
                if ts not in UNCOMPRESSED:
                    compressed_series[study_uid].add(series_dir.name)

    affected = {s: sorted(v) for s, v in compressed_series.items() if v}

    print()
    print("=" * 92)
    print("TRANSFER SYNTAXES FOUND IN LOCAL STORAGE")
    print("=" * 92)
    if not totals:
        print("  no readable DICOM instances found.")
    for uid, n in totals.most_common():
        tag = "uncompressed" if uid in UNCOMPRESSED else "COMPRESSED"
        print(f"  {tag:13} {uid:28} {_ts_name(uid)[:38]:40} {n:>7} instances probed")
    if unreadable:
        print(f"  unreadable/non-DICOM files skipped: {unreadable}")

    print()
    print("=" * 92)
    print("AFFECTED STUDIES (hold compressed pixel data)")
    print("=" * 92)
    if not affected:
        print("  none — every probed instance is uncompressed.")
    else:
        print(f"  {len(affected)} of {len(per_study_series)} studies affected\n")
        for study_uid, series_list in sorted(affected.items()):
            syn = ", ".join(
                f"{_ts_name(u)} x{c}" for u, c in per_study[study_uid].most_common()
                if u not in UNCOMPRESSED
            )
            total_series = len(per_study_series[study_uid])
            print(f"  {study_uid}")
            print(f"      series {len(series_list)}/{total_series} compressed: "
                  f"{', '.join(series_list[:12])}"
                  + (" ..." if len(series_list) > 12 else ""))
            print(f"      {syn}")

    mixed = {
        s: v for s, v in per_study.items()
        if any(u in UNCOMPRESSED for u in v) and any(u not in UNCOMPRESSED for u in v)
    }
    if mixed:
        print()
        print(f"  NOTE: {len(mixed)} study/studies are MIXED (some series compressed, some not):")
        for s in sorted(mixed):
            print(f"    - {s}")

    print()
    print(f"summary: {scanned} instances probed across {len(per_study_series)} studies; "
          f"{len(affected)} affected.")
    if args.sample > 0:
        print(f"         (sampled {args.sample} file(s) per series — use --sample 0 for exhaustive)")

    if args.json:
        payload = {
            "root": str(root),
            "sample_per_series": args.sample,
            "instances_probed": scanned,
            "unreadable": unreadable,
            "transfer_syntax_totals": {u: n for u, n in totals.items()},
            "studies_total": len(per_study_series),
            "studies_affected": len(affected),
            "affected": {
                s: {
                    "compressed_series": v,
                    "series_total": len(per_study_series[s]),
                    "transfer_syntaxes": {
                        u: c for u, c in per_study[s].items() if u not in UNCOMPRESSED
                    },
                }
                for s, v in affected.items()
            },
            "mixed_studies": sorted(mixed),
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"JSON report written: {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
