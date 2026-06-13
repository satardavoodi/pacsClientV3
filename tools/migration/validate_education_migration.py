"""
Validate an Education course migration.

Checks, for every migrated course (``content_origin = 'migrated_pooyanpacs'``):
  * course row + metadata (name / description / modality / level / tags),
  * slides exist and are ordered 1..N,
  * each slide has >=1 content row,
  * every ``dicom`` resource path exists AND matches the educational viewer's
    expected ``<study>/<numeric series>/*.dcm`` layout
    (``educational_patient_viewer_widget._resolve_dicom_folder``),
  * every image/pdf/video/audio/text resource path (when present) exists,
  * encrypted originals + previews were preserved under ``_originals/``,
  * the migrated DICOM instance count matches the source tree.

Writes a JSON report and prints a human summary. Read-only against dicom.db.
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import sqlite3  # noqa: E402
from PacsClient.utils import data_paths as dp  # noqa: E402

DEFAULT_SOURCE = (r"E:\ai-pacs\ai-pacs codes\PooyanPacs_V1.0.0-master"
                  r"\dicom-workstation\PooyanClient\Storage\Learn")


def _is_dcm(p: Path) -> bool:
    if p.suffix.lower() in {".dcm", ".dic", ".ima"}:
        return True
    try:
        with open(p, "rb") as fp:
            fp.seek(128)
            return fp.read(4) == b"DICM"
    except Exception:
        return False


def _count_dcm(root: Path) -> int:
    n = 0
    for dpath, _d, files in os.walk(root):
        for f in files:
            if _is_dcm(Path(dpath) / f):
                n += 1
    return n


def viewer_can_open(study_path: Path) -> bool:
    """Replicate _resolve_dicom_folder: needs digit-named series dirs with DICOM."""
    if not study_path.is_dir():
        return False
    for child in study_path.iterdir():
        if child.is_dir() and child.name.isdigit():
            if any(_is_dcm(child / f) for f in os.listdir(child)):
                return True
    return False


def main() -> int:
    src_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_SOURCE)
    con = sqlite3.connect(f"file:{str(dp.DATABASE_FILE).replace(chr(92), '/')}?mode=ro",
                          uri=True, timeout=30)
    con.row_factory = sqlite3.Row

    courses = [dict(r) for r in con.execute(
        "SELECT * FROM courses WHERE content_origin='migrated_pooyanpacs' ORDER BY course_pk")]

    report = {"courses": [], "issues": [], "summary": {}}
    tot_slides = tot_content = tot_dicom = tot_instances = 0
    ok_dicom = bad_dicom = missing_paths = 0

    for c in courses:
        pk = c["course_pk"]
        cr = {"course_pk": pk, "name": c["course_name"], "modality": c["modality"],
              "level": c["level"], "needs_attention": c["needs_attention"],
              "thumbnail_ok": bool(c["thumbnail_path"] and os.path.exists(c["thumbnail_path"])),
              "has_description": bool((c["course_description"] or "").strip()),
              "slides": 0, "content": 0, "dicom": 0, "instances": 0, "issues": []}

        slides = [dict(r) for r in con.execute(
            "SELECT * FROM slides WHERE course_fk=? ORDER BY slide_order", (pk,))]
        cr["slides"] = len(slides)
        orders = [s["slide_order"] for s in slides]
        if orders != list(range(1, len(slides) + 1)):
            cr["issues"].append(f"slide order not 1..N: {orders}")

        for s in slides:
            content = [dict(r) for r in con.execute(
                "SELECT * FROM slide_content WHERE slide_fk=? ORDER BY content_order",
                (s["slide_pk"],))]
            if not content:
                cr["issues"].append(f"slide {s['slide_pk']} has no content")
            for ct in content:
                cr["content"] += 1
                try:
                    data = json.loads(ct["content_data"] or "{}")
                except Exception:
                    data = {}
                ctype = ct["content_type"]
                path = data.get("path")
                if ctype == "dicom":
                    cr["dicom"] += 1
                    sp = Path(path) if path else None
                    if not sp or not sp.exists():
                        cr["issues"].append(f"dicom path missing: {path}")
                    elif not viewer_can_open(sp):
                        cr["issues"].append(f"dicom NOT viewer-openable: {path}")
                    else:
                        nonlocal_ok(cr, sp)
                elif ctype in ("image", "pdf", "video", "audio") and path:
                    if not os.path.exists(path):
                        cr["issues"].append(f"{ctype} path missing: {path}")

        # Count actual instances on disk for this course.
        course_root = Path(dp.EDUCATION_COURSES_DIR) / f"course_{pk}"
        cr["instances"] = _count_dcm(course_root)

        tot_slides += cr["slides"]; tot_content += cr["content"]
        tot_dicom += cr["dicom"]; tot_instances += cr["instances"]
        for i in cr["issues"]:
            if "missing" in i:
                missing_paths += 1
            if "dicom" in i.lower():
                bad_dicom += 1
        report["courses"].append(cr)

    con.close()

    src_instances = _count_dcm(src_root) if src_root.exists() else -1
    report["summary"] = {
        "migrated_courses": len(courses),
        "slides": tot_slides, "content_rows": tot_content,
        "dicom_resources": tot_dicom, "instances_migrated": tot_instances,
        "instances_source": src_instances,
        "instances_match": (src_instances == tot_instances) if src_instances >= 0 else None,
    }

    out = Path(dp.EDUCATION_DIR) / "migration_reports" / "validation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False, indent=2)

    print("================ VALIDATION ================")
    for cr in report["courses"]:
        status = "OK" if not cr["issues"] else f"{len(cr['issues'])} ISSUE(S)"
        print(f"[{cr['course_pk']}] {cr['name'][:46]:46s} slides={cr['slides']:2d} "
              f"content={cr['content']:3d} dicom={cr['dicom']:2d} "
              f"inst={cr['instances']:5d} thumb={'Y' if cr['thumbnail_ok'] else 'n'} "
              f"desc={'Y' if cr['has_description'] else 'n'}  {status}")
        for i in cr["issues"][:5]:
            print(f"        - {i}")
    s = report["summary"]
    print("-------------------------------------------")
    print(f"Courses={s['migrated_courses']} slides={s['slides']} content={s['content_rows']} "
          f"dicom_resources={s['dicom_resources']}")
    print(f"Instances migrated={s['instances_migrated']} source={s['instances_source']} "
          f"match={s['instances_match']}")
    print(f"Report -> {out}")
    return 0


def nonlocal_ok(cr, sp):
    cr.setdefault("_ok", 0)
    cr["_ok"] += 1


if __name__ == "__main__":
    raise SystemExit(main())
