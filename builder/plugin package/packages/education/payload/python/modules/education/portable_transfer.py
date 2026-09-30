"""Private, local Education transfer packages. Blocking API: run on a worker.

Only Education records are imported, with new primary keys in one transaction.
Media is staged and verified before any database mutation. No PACS database,
credentials, cloud identity, or consultation state is restored by this format.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile

from PacsClient.utils.database import get_db_connection

FORMAT = "ai-pacs-education-transfer"
VERSION = 2
CHUNK = 1024 * 1024
MAX_MANIFEST = 32 * CHUNK
MAX_FILES = 500000
JSON_FIELDS = {"content_data", "layout_position"}
PATH_FIELDS = {"path", "thumbnail_path", "dicom_folder_path", "import_manifest_path"}


class TransferError(ValueError):
    """A safe, user-facing error without clinical identifiers or source paths."""


class TransferCancelled(TransferError):
    pass


def _check(cancel):
    if cancel and cancel():
        raise TransferCancelled("Transfer cancelled. Existing content was not changed.")


def _safe_name(name):
    parts = PurePosixPath(name).parts
    if (not parts or name.startswith("/") or "\\" in name
            or any(p in {".", ".."} or p.endswith((".", " "))
                   or re.search(r'[<>:"|?*\x00-\x1f]', p)
                   or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", p)
                   for p in parts)
            or str(PurePosixPath(name)) != name):
        raise TransferError("The package contains an unsafe file name.")
    return name


def _rows(conn, table, where="", params=()):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} {where}", params)]


def _snapshot(include_courses, include_cases):
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        courses = _rows(conn, "courses") if include_courses else []
        for course in courses:
            course["slides"] = _rows(conn, "slides", "WHERE course_fk=? ORDER BY slide_order", (course["course_pk"],))
            for slide in course["slides"]:
                slide["content"] = _rows(conn, "slide_content", "WHERE slide_fk=? ORDER BY content_order", (slide["slide_pk"],))
                for item in slide["content"]:
                    for key in JSON_FIELDS:
                        if item.get(key):
                            item[key] = json.loads(item[key])
        cases = _rows(conn, "case_of_day_entries") if include_cases else []
        # Keep archived originals on subsequent transfers, even if no slide
        # directly references those files. Receipts belong to Education only.
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='education_portable_imports'").fetchone():
            roots = {}
            for receipt in conn.execute("SELECT assets_json FROM education_portable_imports"):
                roots.update(json.loads(receipt[0]))
            for kind, records, pk in (("courses", courses, "course_pk"), ("cases", cases, "case_pk")):
                for record in records:
                    saved = roots.get(f"{kind}:{record[pk]}")
                    if saved:
                        record["asset_trees"] = saved
        conn.rollback()
    return {"courses": courses, "cases": cases}


class _Assets:
    def __init__(self, archive, progress, cancel, forbidden):
        self.archive, self.progress, self.cancel = archive, progress, cancel
        self.roots = []
        self.files = {}
        self.directories = set()
        self.forbidden = forbidden
        self.last_progress = 0

    def add(self, source):
        path = Path(source)
        if not path.exists():
            raise TransferError("A referenced local file or folder is missing. Restore it before exporting.")
        if path.is_symlink() or path.is_junction():
            raise TransferError("Linked media folders are not supported. Copy the media locally first.")
        path = path.resolve()
        if any(p == path or (path.is_dir() and p.is_relative_to(path)) for p in self.forbidden):
            raise TransferError("Choose an export location outside all included media folders.")
        for root, target in self.roots:
            if path == root or (root.is_dir() and path.is_relative_to(root)):
                return {"$asset": target + ("/" + path.relative_to(root).as_posix() if path != root else "")}
        target = f"assets/{len(self.roots):06d}/{_safe_name(path.name)}"
        self.roots.append((path, target))
        self._copy(path, target)
        return {"$asset": target}

    def _copy(self, path, target):
        _check(self.cancel)
        _safe_name(target)
        if path.is_symlink() or path.is_junction():
            raise TransferError("Linked media folders are not supported. Copy the media locally first.")
        if path.is_dir():
            self.directories.add(target)
            for child in sorted(path.iterdir()):
                self._copy(child, target + "/" + child.name)
            return
        if not path.is_file():
            raise TransferError("An educational resource is not a regular file.")
        before = path.stat()
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as src, self.archive.open(target, "w", force_zip64=True) as dest:
            while block := src.read(CHUNK):
                _check(self.cancel)
                dest.write(block)
                digest.update(block)
                size += len(block)
        after = path.stat()
        if before.st_size != size or before.st_mtime_ns != after.st_mtime_ns:
            raise TransferError("Media changed during export. Finish editing and export again.")
        self.files[target] = {"size": size, "sha256": digest.hexdigest()}
        if self.progress and time.monotonic() - self.last_progress >= 0.1:
            self.progress(f"Packed {len(self.files)} files")
            self.last_progress = time.monotonic()

    def rewrite(self, value):
        if isinstance(value, list):
            return [self.rewrite(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, val in value.items():
            if key in {"import_source_path", "original_source_path"}:
                result[key] = ""  # Historical locations are not runtime dependencies.
            elif key in PATH_FIELDS and isinstance(val, str) and val:
                result[key] = self.add(val)
            else:
                result[key] = self.rewrite(val)
        return result


def export_package(destination, *, include_courses=True, include_cases=True, allow_editing=True, progress=None, cancel=None):
    from PacsClient.utils.config import EDUCATION_STORAGE_PATH, SOURCE_PATH
    from modules.education.case_of_day_database import resolve_case_package_dir

    data = _snapshot(include_courses, include_cases)
    if not data["courses"] and not data["cases"]:
        raise TransferError("There is no saved local content in the selected categories.")
    destination = Path(destination).resolve()
    # Never place the growing archive inside a tree that will be exported.
    roots = [Path(EDUCATION_STORAGE_PATH).resolve(), Path(SOURCE_PATH).resolve()]
    roots += [Path(c["dicom_folder_path"]).resolve().parent for c in data["cases"] if c.get("dicom_folder_path")]
    if any(destination.is_relative_to(root) for root in roots):
        raise TransferError("Choose an export location outside the Education and DICOM media folders.")
    fd, temp = tempfile.mkstemp(prefix=".education-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            assets = _Assets(archive, progress, cancel, (destination, Path(temp).resolve()))
            for course in data["courses"]:
                course["is_editable"] = int(bool(course.get("is_editable", True)) and allow_editing)
                trees = [assets.add(p) for p in course.get("asset_trees", [])]
                storage = Path(EDUCATION_STORAGE_PATH) / f"course_{course['course_pk']}"
                if storage.is_dir():
                    trees.append(assets.add(storage))
                course["asset_trees"] = trees
                for slide in course["slides"]:
                    for item in slide["content"]:
                        if item["content_type"] in {"dicom_study", "dicom_series"}:
                            payload = item["content_data"]
                            uid = str(payload.get("study_uid") or "")
                            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", uid):
                                raise TransferError("A DICOM item has an invalid study reference.")
                            source = Path(SOURCE_PATH) / uid
                            series = payload.get("series_number")
                            if item["content_type"] == "dicom_series":
                                if series is None or not (source / str(int(series))).is_dir():
                                    raise TransferError("A referenced DICOM series is unavailable locally.")
                            if not source.is_dir() or not any(source.rglob("*.dcm")):
                                raise TransferError("A referenced DICOM study is unavailable locally.")
                            payload["path"] = str(source)
                            item["content_type"] = "dicom"
            for case in data["cases"]:
                trees = [assets.add(p) for p in case.get("asset_trees", [])]
                folder = case.get("dicom_folder_path")
                if folder:
                    package = resolve_case_package_dir(folder)
                    if package:
                        trees.append(assets.add(package))
                case["asset_trees"] = trees
            data = assets.rewrite(data)
            manifest = dict(format=FORMAT, version=VERSION, package_id=str(uuid.uuid4()),
                            files=assets.files, directories=sorted(assets.directories), **data)
            raw = json.dumps(manifest, ensure_ascii=True).encode("utf-8")
            if len(raw) > MAX_MANIFEST or len(assets.files) > MAX_FILES:
                raise TransferError("This collection exceeds the transfer package limits.")
            archive.writestr("manifest.json", raw)
        _check(cancel)
        os.replace(temp, destination)
        return {"courses": len(data["courses"]), "cases": len(data["cases"]), "files": len(assets.files)}
    finally:
        Path(temp).unlink(missing_ok=True)


def _restore(value, folder):
    if isinstance(value, dict):
        if set(value) == {"$asset"}:
            name = _safe_name(value["$asset"])
            if not name.startswith("assets/") or not (folder / name).exists():
                raise TransferError("The package references missing media.")
            return str(folder / name)
        result = {}
        for key, val in value.items():
            if key == "asset_trees" and (not isinstance(val, list) or any(not isinstance(v, dict) or set(v) != {"$asset"} for v in val)):
                raise TransferError("The package contains an invalid archived media tree.")
            if key in PATH_FIELDS and val and not (isinstance(val, dict) and set(val) == {"$asset"}):
                raise TransferError("A media reference is not contained in this package.")
            if key in {"import_source_path", "original_source_path"} and val:
                raise TransferError("The package contains an external source reference.")
            result[key] = _restore(val, folder)
        return result
    if isinstance(value, list):
        return [_restore(v, folder) for v in value]
    return value


def _insert(conn, table, record, omit):
    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    values = {k: v for k, v in record.items() if k not in omit}
    if not values or not set(values) <= columns:
        raise TransferError("The package requires an incompatible Education database version.")
    for key in JSON_FIELDS & values.keys():
        if values[key] is not None:
            values[key] = json.dumps(values[key])
    names = ",".join('"' + key + '"' for key in values)
    return conn.execute(f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in values)})", list(values.values())).lastrowid


def import_package(source, *, progress=None, cancel=None):
    from PacsClient.utils.data_paths import EDUCATION_DIR

    root = Path(EDUCATION_DIR) / "transfers"
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=root))
    final = root / ("package_" + uuid.uuid4().hex)
    published = False
    committed = False
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            names = [_safe_name(i.filename) for i in infos]
            if len(infos) > MAX_FILES + 1 or len({n.casefold() for n in names}) != len(names):
                raise TransferError("The package contains duplicate files or too many entries.")
            if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
                raise TransferError("The Education package manifest is missing or too large.")
            raw = archive.read("manifest.json")
            manifest = json.loads(raw)
            if manifest.get("format") != FORMAT or manifest.get("version") not in {1, VERSION}:
                raise TransferError("This is not a supported Education transfer package.")
            package_id = str(uuid.UUID(manifest["package_id"]))
            fingerprint = hashlib.sha256(raw).hexdigest()
            files = manifest["files"]
            if set(names) != set(files) | {"manifest.json"}:
                raise TransferError("The package file inventory does not match its manifest.")
            needed = sum(i.file_size for i in infos)
            if needed + 64 * CHUNK > shutil.disk_usage(root).free:
                raise TransferError("There is not enough free space to import this package.")
            for directory in manifest["directories"]:
                _safe_name(directory)
                if not directory.startswith("assets/"):
                    raise TransferError("The package contains an invalid media directory.")
                (stage / directory).mkdir(parents=True, exist_ok=True)
            last_progress = 0
            for index, (name, expected) in enumerate(files.items(), 1):
                _check(cancel)
                info = archive.getinfo(name)
                if not name.startswith("assets/") or info.file_size != expected["size"] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise TransferError("The package contains invalid media entries.")
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(info) as src, target.open("xb") as dst:
                    while block := src.read(CHUNK):
                        _check(cancel)
                        dst.write(block)
                        digest.update(block)
                if digest.hexdigest() != expected["sha256"]:
                    raise TransferError("Media verification failed. Copy the package again.")
                if progress and time.monotonic() - last_progress >= 0.1:
                    progress(f"Verified {index} of {len(files)} files")
                    last_progress = time.monotonic()
        # Validate references against staging before publishing. Then rebase them.
        _restore(manifest["courses"], stage)
        _restore(manifest["cases"], stage)
        _check(cancel)
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS education_portable_imports (package_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, assets_json TEXT NOT NULL, imported_at TEXT DEFAULT CURRENT_TIMESTAMP)")
                previous = conn.execute("SELECT fingerprint FROM education_portable_imports WHERE package_id=?", (package_id,)).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise TransferError("This package identity was already imported with different contents.")
                    conn.rollback()
                    return {"courses": 0, "cases": 0, "files": 0, "already_imported": True}
                stage.rename(final)
                published = True
                courses = _restore(manifest["courses"], final)
                cases = _restore(manifest["cases"], final)
                asset_roots = {}
                for course in courses:
                    _check(cancel)
                    course_pk = _insert(conn, "courses", course, {"course_pk", "slides", "asset_trees"})
                    if course.get("asset_trees"):
                        asset_roots[f"courses:{course_pk}"] = list(dict.fromkeys(course["asset_trees"]))
                    for slide in course["slides"]:
                        slide["course_fk"] = course_pk
                        slide_pk = _insert(conn, "slides", slide, {"slide_pk", "content"})
                        for item in slide["content"]:
                            item["slide_fk"] = slide_pk
                            _insert(conn, "slide_content", item, {"content_pk"})
                for case in cases:
                    _check(cancel)
                    case_pk = _insert(conn, "case_of_day_entries", case, {"case_pk", "asset_trees"})
                    if case.get("asset_trees"):
                        asset_roots[f"cases:{case_pk}"] = list(dict.fromkeys(case["asset_trees"]))
                    if case.get("body_part"):
                        conn.execute("INSERT OR IGNORE INTO case_of_day_body_parts(body_part) VALUES (?)", (case["body_part"],))
                conn.execute("INSERT INTO education_portable_imports(package_id, fingerprint, assets_json) VALUES (?,?,?)", (package_id, fingerprint, json.dumps(asset_roots)))
                _check(cancel)
                conn.commit()
                committed = True
                return {"courses": len(courses), "cases": len(cases), "files": len(files)}
            except Exception:
                conn.rollback()
                raise
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise TransferError("The Education package is damaged or incomplete.") from exc
    finally:
        # Both paths are freshly allocated children of this operation's store.
        for owned in (stage, final if published and not committed else None):
            if owned is not None and owned.parent.resolve() == root.resolve() and owned.exists():
                shutil.rmtree(owned)
