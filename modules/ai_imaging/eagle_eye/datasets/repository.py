"""Transactional local dataset catalog; separate from the clinical PACS database."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .definitions import form_fields, validate_template, validate_values


class DatasetError(ValueError):
    """Safe, user-facing validation error without patient payloads or paths."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


class DatasetRepository:
    def __init__(self, root=None):
        # Construction performs no disk I/O. The caller invokes all operations off-thread.
        self.root = Path(root) if root is not None else Path("C:/AI-PACS-Datasets/eagle-eye-workspace")

    @contextmanager
    def _db(self, write=False):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / "catalog.sqlite", timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if db.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise DatasetError("This catalog needs a newer application version.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL,
                    version INTEGER NOT NULL, template TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS templates (
                    dataset_id TEXT NOT NULL REFERENCES datasets(id), version INTEGER NOT NULL,
                    template TEXT NOT NULL, PRIMARY KEY(dataset_id, version));
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    namespace TEXT NOT NULL, study_uid TEXT NOT NULL,
                    document TEXT NOT NULL,
                    UNIQUE(dataset_id, namespace, study_uid));
                CREATE TABLE IF NOT EXISTS case_revisions (
                    case_id TEXT NOT NULL REFERENCES cases(id), revision INTEGER NOT NULL,
                    document TEXT NOT NULL, PRIMARY KEY(case_id, revision));
                PRAGMA user_version=1;
            """)
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_datasets(self):
        with self._db() as db:
            return [dict(id=row["id"], version=row["version"], template=json.loads(row["template"]),
                         case_count=row["n"]) for row in db.execute(
                "SELECT d.*, (SELECT COUNT(*) FROM cases c WHERE c.dataset_id=d.id) n FROM datasets d ORDER BY catalog_key")]

    def create_dataset(self, template):
        return self._save_template(None, template, None)

    def update_dataset(self, dataset_id, template, expected_version):
        return self._save_template(dataset_id, template, expected_version)

    def _save_template(self, dataset_id, template, expected_version):
        try:
            template = validate_template(template)
        except ValueError as exc:
            raise DatasetError(str(exc)) from None
        key = _json([template[k].casefold() for k in ("modality", "anatomy", "name")])
        with self._db(write=True) as db:
            version = 1
            if dataset_id:
                old = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
                if old is None or old["version"] != expected_version:
                    raise DatasetError("The dataset changed. Reload it before editing the template.")
                previous = json.loads(old["template"])
                if any(previous[k] != template[k] for k in ("modality", "anatomy")) and db.execute(
                        "SELECT 1 FROM cases WHERE dataset_id=? LIMIT 1", (dataset_id,)).fetchone():
                    raise DatasetError("Create another dataset to change modality or anatomy after adding cases.")
                version = old["version"] + 1
            else:
                dataset_id = uuid.uuid4().hex
            try:
                db.execute("INSERT INTO datasets VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                           "catalog_key=excluded.catalog_key, version=excluded.version, template=excluded.template",
                           (dataset_id, key, version, _json(template)))
            except sqlite3.IntegrityError:
                raise DatasetError("A dataset with that name, modality and anatomy already exists.") from None
            db.execute("INSERT INTO templates VALUES(?,?,?)", (dataset_id, version, _json(template)))
        return {"id": dataset_id, "version": version, "template": template}

    def add_case(self, dataset_id, context):
        required = ("study_uid", "patient_id", "modality", "source_namespace")
        if any(not isinstance(context.get(k), str) or not context[k].strip() for k in required):
            raise DatasetError("The current study identity is incomplete. Load the study before adding it.")
        context = {k: str(context.get(k) or "").strip()[:500] for k in
                   (*required, "patient_name", "study_date", "study_description")}
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            if row is None:
                raise DatasetError("Select an existing dataset.")
            template = json.loads(row["template"])
            modality = context["modality"].upper().replace("MRI", "MR")
            if modality != template["modality"]:
                raise DatasetError("The study modality does not match the selected dataset.")
            existing = db.execute("SELECT document FROM cases WHERE dataset_id=? AND namespace=? AND study_uid=?",
                                  (dataset_id, context["source_namespace"], context["study_uid"])).fetchone()
            if existing:
                document = json.loads(existing[0])
                if document["patient_id"] != context["patient_id"]:
                    raise DatasetError("The saved study identity conflicts with the current patient identity.")
                return document
            document = dict(context, id=uuid.uuid4().hex, dataset_id=dataset_id,
                            template_version=row["version"], template=template, revision=1,
                            values={}, status="draft", reviewer="", saved_utc=_now(),
                            annotation_origin="manual_form", training_eligible=False)
            db.execute("INSERT INTO cases VALUES(?,?,?,?,?)", (document["id"], dataset_id,
                       context["source_namespace"], context["study_uid"], _json(document)))
            db.execute("INSERT INTO case_revisions VALUES(?,?,?)", (document["id"], 1, _json(document)))
        return document

    def get_case(self, case_id):
        with self._db() as db:
            return self._get_case(db, case_id)

    @staticmethod
    def _get_case(db, case_id):
        row = db.execute("SELECT document FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise DatasetError("The case is no longer available. Refresh the case list.")
        return json.loads(row[0])

    def list_cases(self, dataset_id):
        with self._db() as db:
            result = []
            for row in db.execute("SELECT document FROM cases WHERE dataset_id=? ORDER BY rowid DESC", (dataset_id,)):
                case = json.loads(row[0])
                result.append({k: case[k] for k in ("id", "patient_id", "patient_name", "study_date",
                               "study_description", "status", "saved_utc", "template_version")})
                result[-1].update(filled=len(case["values"]), total=len(dict(form_fields(case["template"]))))
            return result

    def save_case(self, case_id, values, status, reviewer, expected_revision):
        if status not in ("draft", "complete"):
            raise DatasetError("Invalid form status.")
        reviewer = str(reviewer or "").strip()[:160]
        if status == "complete" and not reviewer:
            raise DatasetError("Enter the form author's name before marking it complete.")
        with self._db(write=True) as db:
            document = self._get_case(db, case_id)
            if document["revision"] != expected_revision:
                raise DatasetError("The case changed in another window. Reopen it before saving.")
            try:
                values = validate_values(document["template"], values, status == "complete")
            except ValueError as exc:
                raise DatasetError(str(exc)) from None
            document.update(values=values, status=status, reviewer=reviewer,
                            revision=document["revision"] + 1, saved_utc=_now(), training_eligible=False)
            db.execute("UPDATE cases SET document=? WHERE id=?", (_json(document), case_id))
            db.execute("INSERT INTO case_revisions VALUES(?,?,?)", (case_id, document["revision"], _json(document)))
        return document

    def case_history(self, case_id):
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT document FROM case_revisions WHERE case_id=? ORDER BY revision", (case_id,))]


def load_study_context(study_uid):
    """Read the workspace study in a worker; never use a selected widget's other patient."""
    from database.manager import get_patient_by_study_uid, get_study_by_study_uid
    patient = get_patient_by_study_uid(study_uid) or {}
    study = get_study_by_study_uid(study_uid) or {}
    if not patient.get("patient_id") or not study:
        raise DatasetError("This study is not available locally. Load it in Eagle Eye first.")
    return {"study_uid": study_uid, "source_namespace": "local-pacs",
            **{k: str(patient.get(k) or "") for k in ("patient_id", "patient_name")},
            **{k: str(study.get(k) or "") for k in ("modality", "study_date", "study_description")}}
