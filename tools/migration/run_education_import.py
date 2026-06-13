"""
Education course migration runner (CLI).

Imports an external "Learn" course package (PooyanPacs schema 1.1 or a plain
folder tree) into the AI-PACS Education module using
``modules.education.course_importer.EducationCourseImporter``.

Examples
--------
Dry-run a single course (no DB writes, no copying)::

    python tools/migration/run_education_import.py --root "<Learn>" --course Course-3 --dry-run

Dry-run everything::

    python tools/migration/run_education_import.py --root "<Learn>" --dry-run

Full migration with curated enrichment overrides, deleting the demo courses::

    python tools/migration/run_education_import.py --root "<Learn>" \
        --overrides tools/migration/enrichment_overrides.json --delete-demos --yes
"""

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

DEFAULT_ROOT = (r"E:\ai-pacs\ai-pacs codes\PooyanPacs_V1.0.0-master"
                r"\dicom-workstation\PooyanClient\Storage\Learn")


def _progress(msg: str) -> None:
    print(msg, flush=True)


def delete_demo_courses(apply: bool) -> None:
    """Delete demo/seed courses (those with no slides AND no real content)."""
    from modules.education.course_database import (
        get_all_courses, get_slides_for_course, delete_course,
    )
    from PacsClient.utils.config import EDUCATION_STORAGE_PATH
    import shutil

    removed = []
    for c in get_all_courses():
        pk = c["course_pk"]
        origin = str(c.get("content_origin") or "")
        if origin == "migrated_pooyanpacs":
            continue  # never touch freshly migrated content
        slides = get_slides_for_course(pk)
        if slides:
            continue  # has authored content -> keep
        removed.append((pk, c.get("course_name", "")))
        if apply:
            delete_course(pk)
            folder = Path(EDUCATION_STORAGE_PATH) / f"course_{pk}"
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)

    verb = "Deleted" if apply else "Would delete"
    print(f"{verb} {len(removed)} demo course(s):")
    for pk, name in removed:
        print(f"   - [{pk}] {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description="AI-PACS Education course migration")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="Learn root folder")
    ap.add_argument("--course", default=None, help="Only this course folder name")
    ap.add_argument("--overrides", default=None, help="Curated enrichment overrides JSON")
    ap.add_argument("--dry-run", action="store_true", help="Scan + report only")
    ap.add_argument("--delete-demos", action="store_true",
                    help="Delete empty demo/seed courses first")
    ap.add_argument("--reenrich", action="store_true",
                    help="Re-enrich already-imported courses in place (no re-copy)")
    ap.add_argument("--yes", action="store_true", help="Apply destructive actions")
    args = ap.parse_args()

    from modules.education.course_importer import (
        EducationCourseImporter, ImportConfig,
    )

    overrides = {}
    if args.overrides:
        with open(args.overrides, "r", encoding="utf-8") as fp:
            overrides = json.load(fp)
        print(f"Loaded overrides for {len(overrides)} course key(s).")

    if args.reenrich:
        cfg = ImportConfig(overrides=overrides, progress=_progress)
        summaries = EducationCourseImporter(cfg).reenrich_existing()
        print("\n================ RE-ENRICH SUMMARY ================")
        for s in summaries:
            print(f"  pk={s.get('course_pk')}: {s.get('name', s.get('skipped',''))} "
                  f"slides={s.get('slides_updated','-')}/{s.get('slides_total','-')} "
                  f"needs_review={s.get('needs_review','-')}")
        return 0

    if args.delete_demos:
        delete_demo_courses(apply=(args.yes and not args.dry_run))

    cfg = ImportConfig(overrides=overrides, dry_run=args.dry_run, progress=_progress)
    importer = EducationCourseImporter(cfg)

    root = Path(args.root)
    if args.course:
        target = root / args.course
        results = [importer.import_course_package(target)]
        importer._write_run_report()
    else:
        results = importer.import_learn_root(str(root))

    print("\n================ SUMMARY ================")
    total_bytes = 0
    for r in results:
        total_bytes += r.bytes_copied
        flag = " [SKIPPED]" if r.skipped else ""
        print(f"[{r.course_pk}] {r.course_name}{flag}: items={r.item_count} "
              f"resources={r.resource_count} dicom={r.dicom_studies} "
              f"images={r.images} docs={r.documents} enc={r.encrypted_archived} "
              f"copied={r.bytes_copied/1e6:.0f}MB warn={len(r.warnings)} err={len(r.errors)}")
        for w in r.warnings[:5]:
            print(f"      warn: {w}")
        for e in r.errors:
            print(f"      ERR: {e}")
    print(f"Total copied: {total_bytes/1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
