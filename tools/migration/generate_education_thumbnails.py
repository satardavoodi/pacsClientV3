"""
Generate per-series thumbnail PNGs for migrated Education DICOM studies.

The series-thumbnail rail in the patient/education viewer reads pre-rendered PNGs
from ``THUMBNAIL_PATH/<study_uid>/<series_number>.png`` (via
``check_and_get_thumbnails`` / ``show_exist_thumbnails``).  Server-downloaded
studies get these from the server; locally-migrated education studies have only
raw DICOM, so the rail was empty.  This tool renders one representative slice per
series into that canonical location so the EXISTING rail code populates -- "like
any other place in the app".

Idempotent: skips series whose PNG already exists unless --force.

    python tools/migration/generate_education_thumbnails.py [--force] [--course PK]
"""

import argparse
import io
import json
import os
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import sqlite3  # noqa: E402
import numpy as np  # noqa: E402
import pydicom  # noqa: E402
from PIL import Image  # noqa: E402
from PacsClient.utils import data_paths as dp  # noqa: E402

try:
    from PacsClient.utils.config import THUMBNAIL_PATH as _THUMBS
except Exception:
    _THUMBS = getattr(dp, "THUMBNAILS_DIR", dp.USER_DATA_ROOT / "patients" / "thumbnails")
THUMBNAIL_PATH = Path(_THUMBS)

SIZE = 160


def _is_dcm(p: Path) -> bool:
    if p.suffix.lower() in (".dcm", ".dic", ".ima"):
        return True
    try:
        with open(p, "rb") as fp:
            fp.seek(128)
            return fp.read(4) == b"DICM"
    except Exception:
        return False


def render_png_bytes(dcm_path: Path):
    """Render a DICOM slice to small PNG bytes (windowed, 8-bit)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = pydicom.dcmread(str(dcm_path), force=True)
        arr = ds.pixel_array
    arr = np.asarray(arr)
    if arr.ndim == 3 and arr.shape[-1] in (3, 4):  # RGB/RGBA
        pil = Image.fromarray(arr[..., :3].astype(np.uint8), "RGB")
    else:
        if arr.ndim == 3:  # multi-frame mono -> middle frame
            arr = arr[arr.shape[0] // 2]
        arr = arr.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        arr = arr * slope + intercept
        wc, ww = ds.get("WindowCenter"), ds.get("WindowWidth")
        try:
            if wc is not None and ww is not None:
                wc = float(wc[0] if isinstance(wc, pydicom.multival.MultiValue) else wc)
                ww = float(ww[0] if isinstance(ww, pydicom.multival.MultiValue) else ww)
                lo, hi = wc - ww / 2.0, wc + ww / 2.0
            else:
                raise ValueError
        except Exception:
            lo, hi = float(np.percentile(arr, 1)), float(np.percentile(arr, 99))
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((arr - lo) / (hi - lo), 0, 1) * 255.0
        img = norm.astype(np.uint8)
        if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
            img = 255 - img
        pil = Image.fromarray(img, "L").convert("RGB")
    pil.thumbnail((SIZE, SIZE))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _rep_file(series_dir: Path):
    files = sorted(p for p in series_dir.iterdir() if p.is_file() and _is_dcm(p))
    return files[len(files) // 2] if files else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--course", type=int, default=None)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{str(dp.DATABASE_FILE).replace(chr(92), '/')}?mode=ro",
                          uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    q = ("SELECT c.course_pk, sc.content_data FROM courses c "
         "JOIN slides s ON s.course_fk=c.course_pk "
         "JOIN slide_content sc ON sc.slide_fk=s.slide_pk "
         "WHERE c.content_origin='migrated_pooyanpacs' AND sc.content_type='dicom'")
    rows = con.execute(q).fetchall()
    con.close()

    made = skipped = failed = studies = 0
    for r in rows:
        if args.course and r["course_pk"] != args.course:
            continue
        try:
            data = json.loads(r["content_data"] or "{}")
        except Exception:
            continue
        study_path = Path(str(data.get("path") or ""))
        study_uid = str(data.get("study_uid") or "").strip()
        if not study_uid or not study_path.is_dir():
            continue
        studies += 1
        out_dir = THUMBNAIL_PATH / study_uid
        out_dir.mkdir(parents=True, exist_ok=True)
        for series_dir in sorted(p for p in study_path.iterdir() if p.is_dir() and p.name.isdigit()):
            out = out_dir / f"{series_dir.name}.png"
            if out.exists() and not args.force:
                skipped += 1
                continue
            rep = _rep_file(series_dir)
            if not rep:
                continue
            try:
                out.write_bytes(render_png_bytes(rep))
                made += 1
            except Exception as exc:
                failed += 1
                if failed <= 8:
                    print(f"  FAIL {series_dir}: {exc}")
        print(f"  course {r['course_pk']} study {study_uid[:24]}… -> {out_dir}", flush=True)

    print(f"\nDONE studies={studies} thumbnails_made={made} skipped={skipped} failed={failed}")
    print(f"THUMBNAIL_PATH={THUMBNAIL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
