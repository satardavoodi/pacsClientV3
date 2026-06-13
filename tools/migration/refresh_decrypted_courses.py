"""
Surgical re-import / refresh of newly-decrypted E-Learning attachments.

Background
----------
The PooyanPacs "Learn" source was re-exported with **all** attachment types
decrypted (previously only DICOM was). The runtime education structure
(``user_data/education/courses/course_<pk>/``) still holds the OLD encrypted
attachments (``.IPcryp`` / ``.IPdcom`` / ``.IPe``) under each item's
``_originals/``, and many ``slide_content`` rows reference those encrypted files
via an "Encrypted originals (archived)" placeholder.

This tool refreshes the current structure **in place**, course by course:

  * maps runtime ``course_<pk>`` -> source course folder (``migration_manifest.json``),
  * reads each source ``item.json`` (schema 1.2 -- plain, decrypted files),
  * copies the decrypted non-DICOM attachments into the runtime item
    ``_originals/`` (safe overwrite by size + SHA1; never clobbers a newer file),
  * retires the matching encrypted ``.IPcryp/.IPdcom/.IPe`` files to
    ``_originals/_legacy_encrypted/`` (MOVED, never deleted),
  * rewrites the slide's ``slide_content`` rows to point at the decrypted files
    (removing the encrypted placeholder; rows tagged ``origin=elearning_refresh``
    so the tool is idempotent / re-runnable),
  * writes ``course.json`` (course root) and ``item.json`` (each item folder)
    describing the decrypted resources with relative paths, a
    ``legacy/protectedFiles`` section and warnings.

Safety
------
* Dry-run by DEFAULT. ``--apply`` is required to write anything.
* ``--apply`` backs up ``dicom.db`` to ``backups/`` before the first DB write.
* Encrypted files are MOVED to ``_legacy_encrypted/`` -- never deleted.
* A full JSON action report is written under ``user_data/education/migration_reports/``.

Usage
-----
    python tools/migration/refresh_decrypted_courses.py --dry-run
    python tools/migration/refresh_decrypted_courses.py --course course_9 --dry-run
    python tools/migration/refresh_decrypted_courses.py --apply
    python tools/migration/refresh_decrypted_courses.py --validate
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

DEFAULT_SRC = (r"E:\ai-pacs\ai-pacs codes\PooyanPacs_V1.0.0-master"
               r"\dicom-workstation\PooyanClient\Storage\Learn")

ORIGIN_TAG = "elearning_refresh"
ENCRYPTED_EXTS = {".ipcryp", ".ipdcom", ".ipe"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
PDF_EXTS = {".pdf"}
PRESENTATION_EXTS = {".ppt", ".pptx"}
DOCUMENT_EXTS = {".doc", ".docx", ".rtf", ".odt"}
LEGACY_DIRNAME = "_legacy_encrypted"

# attachType (from source item.json) -> internal kind
ATTACH_KIND = {
    "image": "image", "pdf": "pdf", "video": "video", "audio": "audio",
    "powerpoint": "presentation", "word": "document",
    "dicoms": "dicom", "dicom": "dicom", "quiz": "quiz",
}


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_compact() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def kind_for_attachment(attach_type: Optional[str], rel_path: str) -> str:
    """Resolve an internal kind from the source attachType, falling back to ext."""
    t = (attach_type or "").strip().lower()
    if t in ATTACH_KIND:
        return ATTACH_KIND[t]
    ext = Path(rel_path or "").suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in PRESENTATION_EXTS:
        return "presentation"
    if ext in DOCUMENT_EXTS:
        return "document"
    return "other"


def content_type_for_kind(kind: str) -> str:
    """Map an internal kind to a slide_content.content_type the viewer renders."""
    return {
        "image": "image", "pdf": "pdf", "video": "video", "audio": "audio",
        "presentation": "attachment", "document": "attachment",
    }.get(kind, "text")


def build_content_data(kind: str, title: str, abs_path: str, source_name: str,
                       run_id: str) -> Dict[str, Any]:
    """Build the slide_content.content_data dict (matches the importer format).

    DB content keeps an ABSOLUTE path (what the viewer expects) plus an
    ``origin``/``run_id`` tag so the refresh rows can be found + replaced on a
    re-run (idempotency).
    """
    base: Dict[str, Any] = {
        "name": title, "path": abs_path, "source_name": source_name,
        "origin": ORIGIN_TAG, "run_id": run_id,
    }
    if kind == "image":
        base["caption"] = title
    elif kind in ("presentation", "document"):
        base["label"] = "Presentation" if kind == "presentation" else "Document"
    elif kind in ("archive", "other"):
        base["text"] = (f"Resource '{source_name}' preserved at the path above. "
                        f"Open it with an external application.")
    return base


def _sha1(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fp:
        for blk in iter(lambda: fp.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def decide_copy(src: Path, dest: Path) -> Tuple[str, str]:
    """Safe-overwrite decision: ('copy'|'skip'|'replace', reason).

    * dest missing                -> copy
    * same size AND same sha1     -> skip (already imported)
    * dest newer than src         -> skip (never clobber a newer valid file)
    * otherwise                   -> replace (back up dest first)
    """
    if not dest.exists():
        return "copy", "missing"
    try:
        s_st, d_st = src.stat(), dest.stat()
    except OSError as exc:
        return "copy", f"stat-failed:{exc}"
    if s_st.st_size == d_st.st_size and _sha1(src) == _sha1(dest):
        return "skip", "identical"
    if d_st.st_mtime > s_st.st_mtime + 1:
        return "skip", "dest-newer"
    return "replace", "differs"


def build_item_json(item_folder: str, resources: List[Dict[str, Any]],
                    protected: List[Dict[str, Any]], warnings: List[str],
                    item_id: Optional[int]) -> Dict[str, Any]:
    return {
        "schemaVersion": "ai-pacs-elearning-1.0",
        "itemFolder": item_folder,
        "itemId": item_id,
        "generatedAtUtc": _now_iso(),
        "resourceCount": len(resources),
        "resources": resources,            # relative paths only
        "protectedFiles": protected,       # legacy encrypted, non-primary
        "warnings": warnings,
    }


def build_course_json(course_pk: int, course_row: Dict[str, Any], source_folder: str,
                      items: List[Dict[str, Any]], resource_summary: Dict[str, int],
                      warnings: List[str]) -> Dict[str, Any]:
    return {
        "schemaVersion": "ai-pacs-elearning-1.0",
        "courseId": course_pk,
        "title": course_row.get("course_name", f"Course {course_pk}"),
        "description": course_row.get("course_description", ""),
        "category": _parse_json_list(course_row.get("body_regions")),
        "modality": course_row.get("modality", ""),
        "sourceFolder": source_folder,
        "numberOfItems": len(items),
        "items": items,                    # ordered, relative item paths
        "resourceSummary": resource_summary,
        "generatedAtUtc": _now_iso(),
        "warnings": warnings,
    }


def _parse_json_list(val: Any) -> List[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.strip():
        try:
            out = json.loads(val)
            return out if isinstance(out, list) else [str(out)]
        except Exception:
            return [val]
    return []


def is_encrypted_placeholder(content_type: str, content_data: Dict[str, Any]) -> bool:
    """True if a slide_content row is the importer's encrypted-originals placeholder."""
    if content_type != "text" or not isinstance(content_data, dict):
        return False
    name = str(content_data.get("name", ""))
    blob = json.dumps(content_data, ensure_ascii=False).lower()
    return (name.startswith("Encrypted originals")
            or "ipcryp" in blob or "ipdcom" in blob or ".ipe" in blob
            or "encrypted source file" in blob)


def parse_source_item(slide_notes: Optional[str]) -> Optional[str]:
    """Extract the 'Source: Item-XX' folder name from a slide's notes."""
    m = re.search(r"Source:\s*(Item-\d+)", slide_notes or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Refresher
# ---------------------------------------------------------------------------
class CourseRefresher:
    def __init__(self, src_root: str, run_root: str, dry_run: bool = True,
                 progress: Optional[Callable[[str], None]] = None,
                 db: Any = None):
        self.src_root = Path(src_root)
        self.run_root = Path(run_root)
        self.dry_run = dry_run
        self._progress = progress or (lambda m: None)
        self.run_id = _ts_compact()
        self.actions: List[Dict[str, Any]] = []
        self.course_reports: List[Dict[str, Any]] = []
        self._db_backed_up = False
        # Injectable DB layer (defaults to the education course_database module).
        if db is None:
            from modules.education import course_database as db  # type: ignore
        self.db = db

    # -- public ------------------------------------------------------------
    def run(self, only_course: Optional[str] = None) -> List[Dict[str, Any]]:
        # Snapshot the DB before ANY mutation (file copies/moves are reversible;
        # encrypted files are only moved to _legacy_encrypted, never deleted).
        if not self.dry_run:
            self._ensure_db_backup()
        course_dirs = sorted(
            d for d in self.run_root.iterdir()
            if d.is_dir() and d.name.startswith("course_")
        )
        if only_course:
            course_dirs = [d for d in course_dirs if d.name == only_course]
        for cdir in course_dirs:
            try:
                self._refresh_course(cdir)
            except Exception as exc:  # never abort the whole run on one course
                self._progress(f"  ERROR {cdir.name}: {exc}")
                self.course_reports.append({"course": cdir.name, "error": str(exc)})
        self._write_report()
        return self.course_reports

    # -- per course --------------------------------------------------------
    def _refresh_course(self, cdir: Path) -> None:
        manifest = self._load_json(cdir / "migration_manifest.json") or {}
        course_pk = manifest.get("course_pk")
        source_folder = os.path.basename(str(manifest.get("source_folder", "")))
        if course_pk is None or not source_folder:
            self._progress(f"  SKIP {cdir.name}: no manifest mapping")
            return
        src_course = self.src_root / source_folder
        if not src_course.is_dir():
            self._progress(f"  SKIP {cdir.name}: source {source_folder} missing")
            return

        self._progress(f"== {cdir.name} <- {source_folder} (pk={course_pk})")
        course_row = self._get_course_row(course_pk)
        slides = self.db.get_slides_for_course(course_pk)
        slide_by_item = {}
        for s in slides:
            it = parse_source_item(s.get("slide_notes"))
            if it:
                slide_by_item[it] = s

        items_info: List[Dict[str, Any]] = []
        summary = {"image": 0, "pdf": 0, "video": 0, "audio": 0,
                   "presentation": 0, "document": 0, "dicom": 0,
                   "other": 0, "legacy": 0}
        course_warnings: List[str] = []
        # Carry through warnings the decryptor recorded for this course.
        src_course_meta = self._load_json(src_course / "course.json") or {}
        for w in src_course_meta.get("warnings", []) or []:
            course_warnings.append(f"source: {w}")

        assets = cdir / "assets"
        item_dirs = sorted(assets.iterdir()) if assets.is_dir() else []
        for idir in item_dirs:
            if not idir.is_dir():
                continue
            info = self._refresh_item(idir, src_course, slide_by_item.get(idir.name),
                                      summary)
            if info:
                items_info.append(info)

        # course.json
        course_json = build_course_json(
            int(course_pk), course_row, source_folder, items_info, summary,
            course_warnings)
        self._write_json(cdir / "course.json", course_json)
        item_warnings = [w for it in items_info for w in it.get("warnings", [])]
        self.course_reports.append({
            "course": cdir.name, "course_pk": course_pk,
            "source_folder": source_folder, "items": len(items_info),
            "summary": summary, "warnings": course_warnings,
            "item_warnings": item_warnings,
        })

    # -- per item ----------------------------------------------------------
    def _refresh_item(self, idir: Path, src_course: Path, slide: Optional[Dict[str, Any]],
                      summary: Dict[str, int]) -> Optional[Dict[str, Any]]:
        item_name = idir.name
        src_item = src_course / item_name
        src_meta = self._load_json(src_item / "item.json") or {}
        attachments = src_meta.get("attachments", []) if src_item.is_dir() else []
        item_id = src_meta.get("itemId")
        originals = idir / "_originals"
        warnings: List[str] = []
        resources: List[Dict[str, Any]] = []
        db_rows: List[Tuple[str, Dict[str, Any]]] = []  # (content_type, content_data)

        # 1) copy decrypted non-DICOM attachments into _originals/
        for att in attachments:
            rel = att.get("relativePath") or ""
            kind = kind_for_attachment(att.get("attachType"), rel)
            title = att.get("title") or Path(rel).stem
            if kind == "dicom":
                continue  # already materialised as .dcm
            if kind == "quiz" or not rel:
                warnings.append(f"{item_name}: '{att.get('attachType')}' "
                                f"attachment '{title}' has no renderable media")
                continue
            src_file = src_item / rel
            if not src_file.is_file():
                warnings.append(f"{item_name}: source attachment missing: {rel}")
                continue
            ext = src_file.suffix.lower()
            if kind == "image" and ext == ".webp":
                warnings.append(f"{item_name}: webp image '{rel}' may not render on "
                                f"all builds")
            dest = originals / rel
            action, reason = ("copy", "missing") if not dest.exists() else decide_copy(src_file, dest)
            if not self.dry_run and action in ("copy", "replace"):
                originals.mkdir(parents=True, exist_ok=True)
                if action == "replace":
                    self._backup_file(dest)
                shutil.copy2(src_file, dest)
            self._log("copy_attachment", item=item_name, src=str(src_file),
                      dest=str(dest), decision=action, reason=reason, kind=kind)
            rel_to_item = os.path.relpath(dest, idir).replace(os.sep, "/")
            resources.append({"type": kind, "title": title,
                              "relativePath": rel_to_item, "sourceName": Path(rel).name})
            db_rows.append((content_type_for_kind(kind),
                            build_content_data(kind, title, str(dest), Path(rel).name,
                                               self.run_id)))
            summary[kind] = summary.get(kind, 0) + 1

        # 2) retire encrypted leftovers anywhere under _originals/ (incl. nested
        #    Dicom*/.../Config*.IPdcom) -> _legacy_encrypted/<same subpath>.
        protected: List[Dict[str, Any]] = []
        legacy_dir = originals / LEGACY_DIRNAME
        if originals.is_dir():
            for dirpath, _dirs, files in os.walk(originals):
                if LEGACY_DIRNAME in Path(dirpath).parts:
                    continue
                for fn in sorted(files):
                    f = Path(dirpath) / fn
                    if f.suffix.lower() not in ENCRYPTED_EXTS:
                        continue
                    rel_in_orig = f.relative_to(originals)
                    target = legacy_dir / rel_in_orig
                    if not self.dry_run:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            target.unlink()
                        shutil.move(str(f), str(target))
                    self._log("retire_encrypted", item=item_name, src=str(f),
                              dest=str(target))
                    summary["legacy"] = summary.get("legacy", 0) + 1
            # list everything currently parked in legacy (covers re-runs too)
            if legacy_dir.is_dir():
                for dirpath, _dirs, files in os.walk(legacy_dir):
                    for fn in sorted(files):
                        rel_leg = os.path.relpath(Path(dirpath) / fn, idir).replace(os.sep, "/")
                        protected.append({"relativePath": rel_leg, "reason": "encrypted-source"})

        # 3) DICOM resources already present on disk (relative listing)
        dcm_dirs = self._dicom_study_dirs(idir)
        for d in dcm_dirs:
            rel = os.path.relpath(d, idir).replace(os.sep, "/")
            resources.append({"type": "dicom", "title": f"DICOM study ({rel})",
                              "relativePath": rel})
            summary["dicom"] = summary.get("dicom", 0) + 1

        # 4) DB rewrite for the mapped slide
        if slide is not None:
            self._rewrite_slide_content(slide, db_rows)
        elif db_rows:
            warnings.append(f"{item_name}: no slide mapped (Source: tag missing) -- "
                            f"{len(db_rows)} decrypted resource(s) on disk but not "
                            f"wired into the DB")

        # 5) item.json
        item_json = build_item_json(item_name, resources, protected, warnings, item_id)
        self._write_json(idir / "item.json", item_json)
        return {
            "itemId": item_id, "itemFolder": item_name,
            "relativePath": f"assets/{item_name}",
            "resourceCount": len(resources),
            "types": sorted({r["type"] for r in resources}),
            "warnings": warnings,
        }

    # -- DB ----------------------------------------------------------------
    def _rewrite_slide_content(self, slide: Dict[str, Any],
                               db_rows: List[Tuple[str, Dict[str, Any]]]) -> None:
        slide_pk = slide["slide_pk"]
        existing = self.db.get_content_for_slide(slide_pk)
        max_order = 0
        for c in existing:
            cd = c.get("content_data") or {}
            ct = c.get("content_type", "")
            max_order = max(max_order, int(c.get("content_order") or 0))
            # remove encrypted placeholders + our own prior refresh rows (idempotent)
            if is_encrypted_placeholder(ct, cd) or (isinstance(cd, dict)
                                                    and cd.get("origin") == ORIGIN_TAG):
                self._log("db_delete_content", slide_pk=slide_pk,
                          content_pk=c.get("content_pk"), content_type=ct)
                if not self.dry_run:
                    self.db.delete_slide_content(c["content_pk"])
        order = max_order
        for ct, cd in db_rows:
            order += 1
            self._log("db_insert_content", slide_pk=slide_pk, content_type=ct,
                      name=cd.get("name"))
            if not self.dry_run:
                self._ensure_db_backup()
                self.db.insert_slide_content(slide_fk=slide_pk, content_type=ct,
                                             content_order=order, content_data=cd)

    # -- helpers -----------------------------------------------------------
    def _dicom_study_dirs(self, idir: Path) -> List[Path]:
        """Immediate study-level child dirs of the item that contain DICOM."""
        out: List[Path] = []
        for child in sorted(p for p in idir.iterdir() if p.is_dir()):
            if child.name in ("_originals",) or child.name == LEGACY_DIRNAME:
                continue
            has_dcm = any(
                any(f.lower().endswith(".dcm") for f in files)
                for _dp, _d, files in os.walk(child)
            )
            if has_dcm:
                out.append(child)
        return out

    def _get_course_row(self, course_pk: int) -> Dict[str, Any]:
        for c in self.db.get_all_courses():
            if c.get("course_pk") == course_pk:
                return c
        return {}

    def _load_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return None

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        self._log("write_json", path=str(path))
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _backup_file(self, path: Path) -> None:
        if self.dry_run or not path.exists():
            return
        bak = path.with_suffix(path.suffix + f".bak_{self.run_id}")
        try:
            shutil.copy2(path, bak)
        except Exception:
            pass

    def _ensure_db_backup(self) -> None:
        if self._db_backed_up or self.dry_run:
            return
        try:
            from PacsClient.utils.data_paths import DATABASE_FILE
            src = Path(DATABASE_FILE)
            bdir = REPO_ROOT / "backups"
            bdir.mkdir(exist_ok=True)
            dest = bdir / f"dicom_pre-elearning-refresh_{self.run_id}.db"
            shutil.copy2(src, dest)
            self._progress(f"  DB backed up -> {dest}")
            self._log("db_backup", dest=str(dest))
        except Exception as exc:
            self._progress(f"  WARNING: DB backup failed: {exc}")
        self._db_backed_up = True

    def _log(self, action: str, **kw: Any) -> None:
        self.actions.append({"action": action, **kw})

    def _write_report(self) -> Path:
        try:
            from PacsClient.utils.data_paths import EDUCATION_DIR
            rdir = Path(EDUCATION_DIR) / "migration_reports"
        except Exception:
            rdir = REPO_ROOT / "education_migration_reports"
        rdir.mkdir(parents=True, exist_ok=True)
        path = rdir / f"refresh_{self.run_id}{'_dryrun' if self.dry_run else ''}.json"
        payload = {
            "run_id": self.run_id, "generated_at": _now_iso(),
            "dry_run": self.dry_run, "src_root": str(self.src_root),
            "run_root": str(self.run_root), "courses": self.course_reports,
            "action_count": len(self.actions), "actions": self.actions,
        }
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        self._progress(f"Report: {path}")
        return path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_runtime(run_root: str, db: Any = None) -> Dict[str, Any]:
    """Validate decrypted files + JSON + DB after a refresh."""
    if db is None:
        from modules.education import course_database as db  # type: ignore
    run = Path(run_root)
    res = {"images_ok": 0, "images_bad": 0, "pdf_ok": 0, "pdf_bad": 0,
           "pptx_ok": 0, "pptx_bad": 0, "video_seen": 0, "json_ok": 0,
           "json_bad": 0, "encrypted_primary_refs": 0, "issues": []}

    def _hdr(p: Path, n: int = 16) -> bytes:
        try:
            with open(p, "rb") as fp:
                return fp.read(n)
        except Exception:
            return b""

    for dirpath, _dirs, files in os.walk(run):
        if LEGACY_DIRNAME in dirpath:
            continue
        for f in files:
            p = Path(dirpath) / f
            ext = p.suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".webp"):
                h = _hdr(p)
                ok = (h.startswith(b"\xff\xd8\xff") or h.startswith(b"\x89PNG")
                      or h[:4] == b"RIFF")
                res["images_ok" if ok else "images_bad"] += 1
                if not ok:
                    res["issues"].append(f"bad image header: {p}")
            elif ext == ".pdf":
                ok = _hdr(p).startswith(b"%PDF")
                res["pdf_ok" if ok else "pdf_bad"] += 1
                if not ok:
                    res["issues"].append(f"bad PDF header: {p}")
            elif ext in (".pptx", ".ppt"):
                h = _hdr(p)
                # OOXML (.pptx) is a zip (PK..); legacy binary PowerPoint (.ppt,
                # sometimes saved with a .pptx extension) is an OLE2 compound file.
                ok = h.startswith(b"PK") or h.startswith(b"\xd0\xcf\x11\xe0")
                res["pptx_ok" if ok else "pptx_bad"] += 1
                if not ok:
                    res["issues"].append(f"bad PowerPoint header: {p}")
            elif ext in VIDEO_EXTS:
                res["video_seen"] += 1
            elif f in ("course.json", "item.json"):
                try:
                    with open(p, "r", encoding="utf-8") as fp:
                        json.load(fp)
                    res["json_ok"] += 1
                except Exception as exc:
                    res["json_bad"] += 1
                    res["issues"].append(f"bad JSON {p}: {exc}")

    # DB: any remaining primary references to encrypted files?
    try:
        for c in db.get_all_courses():
            for s in db.get_slides_for_course(c["course_pk"]):
                for cc in db.get_content_for_slide(s["slide_pk"]):
                    blob = json.dumps(cc.get("content_data") or {}, ensure_ascii=False).lower()
                    if (".ipcryp" in blob or ".ipdcom" in blob or ".ipe" in blob) and \
                       not is_encrypted_placeholder(cc.get("content_type", ""),
                                                    cc.get("content_data") or {}):
                        res["encrypted_primary_refs"] += 1
                        res["issues"].append(
                            f"DB encrypted ref slide={s['slide_pk']} "
                            f"content={cc.get('content_pk')}")
    except Exception as exc:
        res["issues"].append(f"DB validation failed: {exc}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh decrypted E-Learning attachments")
    ap.add_argument("--src", default=DEFAULT_SRC, help="Decrypted Learn source root")
    ap.add_argument("--course", default=None, help="Only this runtime course_<pk> folder")
    ap.add_argument("--dry-run", action="store_true", help="Scan + report only (default)")
    ap.add_argument("--apply", action="store_true", help="Write files + DB changes")
    ap.add_argument("--validate", action="store_true", help="Validate runtime only")
    args = ap.parse_args()

    from PacsClient.utils.config import EDUCATION_STORAGE_PATH
    run_root = EDUCATION_STORAGE_PATH

    if args.validate:
        rep = validate_runtime(run_root)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0

    dry = not args.apply
    print(f"{'DRY-RUN' if dry else 'APPLY'} | src={args.src}\n        run={run_root}")
    refresher = CourseRefresher(args.src, run_root, dry_run=dry, progress=print)
    reports = refresher.run(only_course=args.course)

    print("\n================ SUMMARY ================")
    agg: Dict[str, int] = {}
    for r in reports:
        if "error" in r:
            print(f"[{r['course']}] ERROR: {r['error']}")
            continue
        s = r["summary"]
        for k, v in s.items():
            agg[k] = agg.get(k, 0) + v
        print(f"[{r['course']}] <- {r['source_folder']}: items={r['items']} "
              f"img={s['image']} pdf={s['pdf']} video={s['video']} "
              f"ppt={s['presentation']} doc={s['document']} dicom={s['dicom']} "
              f"legacy_retired={s['legacy']} "
              f"warn={len(r['warnings']) + len(r.get('item_warnings', []))}")
    print(f"TOT:  {agg}")
    print(f"({'no changes written -- dry run' if dry else 'changes applied'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
