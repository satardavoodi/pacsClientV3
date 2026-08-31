"""On-disk Eagle Eye lumbar capture sessions.

Layout (spec 8 / 11 / 12)::

    user_data/ai/eagle_eye/<StudyInstanceUID>/<session_id>/
        session.json
        series_sources.local.json
        Sagittal/
            manifest.json
            sagittal_001.png ...
        Axial/
            manifest.json
            axial_001.png ...

The manifests are the contract the later analysis stage reads, so every capture
carries enough DICOM identity to reconstruct exactly where the frame came from:
source series UIDs, the SOP Instance UID shown in each pane, the slice position
in patient coordinates and the spatial-context labels.

The optional ``series_sources.local.json`` file contains local DICOM paths for
worker-side evidence composition. It is private provenance and is never part of
the model request document.

Pure python (pathlib + json). Writing an image is delegated to a caller-supplied
callback, so the store itself never imports Qt and is fully testable headless.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from .constants import (
    AXIAL_DIR,
    AXIAL_PREFIX,
    EAGLE_EYE_VERSION,
    MANIFEST_JSON,
    SAGITTAL_DIR,
    SAGITTAL_PREFIX,
    SESSION_JSON,
    SESSION_TYPE_AXIAL,
    SESSION_TYPE_SAGITTAL,
    SLOT_ORDER,
)

logger = logging.getLogger(__name__)

PASS_SAGITTAL = "sagittal"
PASS_AXIAL = "axial"
LOCAL_SERIES_SOURCES_JSON = "series_sources.local.json"


class PassSpec:
    """Where one capture session's output lives on disk.

    Built from a ``protocols.CaptureSession`` so the folder names, filename
    prefixes and manifest ``session_type`` come from the protocol rather than
    from a hardcoded lumbar table. ``for_lumbar()`` is the default a caller
    gets when it does not supply any, which keeps every existing test and the
    lumbar path byte-identical.
    """

    __slots__ = ("name", "directory", "prefix", "session_type")

    def __init__(self, name: str, directory: str, prefix: str, session_type: str):
        self.name = str(name)
        self.directory = str(directory)
        self.prefix = str(prefix)
        self.session_type = str(session_type)

    @classmethod
    def from_capture_session(cls, session: Any) -> "PassSpec":
        return cls(
            name=session.name,
            directory=getattr(session, "directory", "") or session.name.title(),
            prefix=getattr(session, "file_prefix", "") or session.name,
            session_type=getattr(session, "session_type", "") or session.name,
        )

    @staticmethod
    def for_lumbar() -> List["PassSpec"]:
        return [
            PassSpec(PASS_SAGITTAL, SAGITTAL_DIR, SAGITTAL_PREFIX, SESSION_TYPE_SAGITTAL),
            PassSpec(PASS_AXIAL, AXIAL_DIR, AXIAL_PREFIX, SESSION_TYPE_AXIAL),
        ]


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_segment(value: Any, fallback: str) -> str:
    """A single path segment that is safe on every filesystem.

    Study UIDs are dotted digits so they normally pass through untouched; this
    only guards against a malformed or empty UID turning into a traversal or an
    unnamed folder.
    """
    text = _SAFE_SEGMENT.sub("_", str(value or "").strip())
    text = text.strip("._") or fallback
    return text[:128]


def default_session_root() -> Path:
    """``user_data/ai/eagle_eye``, resolved through the app's data paths.

    Falls back to a repo-relative path when the PacsClient config is not
    importable (unit tests, tooling), so this module never hard-depends on the
    application being initialised.
    """
    try:
        from PacsClient.utils.data_paths import AI_DIR
        return Path(AI_DIR) / "eagle_eye"
    except Exception:
        return Path(os.getcwd()) / "user_data" / "ai" / "eagle_eye"


def _utc_now_iso(now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def _session_id(now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class CaptureRecord:
    """One captured 3-panel frame."""

    __slots__ = ("index", "image", "payload")

    def __init__(self, index: int, image: str, payload: Dict[str, Any]):
        self.index = int(index)
        self.image = str(image)
        self.payload = dict(payload or {})

    def as_dict(self) -> Dict[str, Any]:
        data = {"index": self.index, "image": self.image}
        data.update(self.payload)
        return data


class EagleEyeCaptureSession:
    """A single Eagle Eye capture session on disk.

    Usage::

        session = create_session(study_uid)
        session.set_study_context(...)
        session.set_selection(selection_dict)
        session.set_pass_geometry(PASS_SAGITTAL, order_dict)
        path = session.next_capture_path(PASS_SAGITTAL)
        ...write the PNG to `path`...
        session.add_capture(PASS_SAGITTAL, {...})
        session.write()
    """

    def __init__(self, path: Path, study_uid: str, session_id: str, created_at: str,
                 passes: Optional[Sequence[PassSpec]] = None,
                 protocol_id: str = "lumbar_mri"):
        self.path = Path(path)
        self.study_uid = str(study_uid or "")
        self.session_id = str(session_id or "")
        self.created_at = created_at
        self.version = EAGLE_EYE_VERSION
        self.protocol_id = str(protocol_id or "")

        specs = list(passes) if passes else PassSpec.for_lumbar()
        self._passes: Dict[str, PassSpec] = {spec.name: spec for spec in specs}
        self._pass_order: List[str] = [spec.name for spec in specs]

        self._study_context: Dict[str, Any] = {}
        self._selection: Dict[str, Any] = {}
        self._series_sources: Dict[str, Dict[str, Any]] = {}
        self._layout: Dict[str, Any] = {
            "rows": 1,
            "columns": 3,
            "viewports": [
                {"position": i + 1, "slot": slot} for i, slot in enumerate(SLOT_ORDER)
            ],
        }
        self._pass_geometry: Dict[str, Dict[str, Any]] = {n: {} for n in self._pass_order}
        self._captures: Dict[str, List[CaptureRecord]] = {n: [] for n in self._pass_order}
        self._notes: List[str] = []
        self._completed_at: Optional[str] = None

    # -- passes ------------------------------------------------------------

    @property
    def pass_names(self) -> List[str]:
        return list(self._pass_order)

    def set_layout(self, rows: int, columns: int, slots: Sequence[str]) -> None:
        """Record the protocol's layout instead of assuming lumbar's 1x3."""
        self._layout = {
            "rows": int(rows),
            "columns": int(columns),
            "viewports": [
                {"position": i + 1, "slot": slot} for i, slot in enumerate(slots)
            ],
        }

    # -- directories -------------------------------------------------------

    def pass_dir(self, pass_name: str) -> Path:
        return self.path / self._passes[pass_name].directory

    def ensure_dirs(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        for name in self._pass_order:
            self.pass_dir(name).mkdir(parents=True, exist_ok=True)

    # -- context -----------------------------------------------------------

    def set_study_context(self, **fields: Any) -> None:
        """Patient / study identity written into session.json."""
        self._study_context.update({k: v for k, v in fields.items() if v is not None})

    def set_selection(self, selection: Dict[str, Any]) -> None:
        """The full classifier verdict, including alternatives and confidence."""
        self._selection = dict(selection or {})

    def set_series_sources(self, sources: Dict[str, Dict[str, Any]]) -> None:
        """Persist local-only DICOM locations outside the model request contract."""
        self._series_sources = {
            str(role): dict(source)
            for role, source in (sources or {}).items()
            if role and isinstance(source, dict)
        }

    def set_pass_geometry(self, pass_name: str, geometry: Dict[str, Any]) -> None:
        """Capture-order metadata for one pass (direction, axis, slice count)."""
        self._pass_geometry[pass_name] = dict(geometry or {})

    def add_note(self, note: str) -> None:
        if note:
            self._notes.append(str(note))

    # -- captures ----------------------------------------------------------

    def capture_count(self, pass_name: str) -> int:
        return len(self._captures[pass_name])

    def capture_filename(self, pass_name: str, index: int) -> str:
        return f"{self._passes[pass_name].prefix}_{int(index):03d}.png"

    def next_capture_path(self, pass_name: str) -> Path:
        """Path the NEXT capture of this pass should be written to."""
        index = self.capture_count(pass_name) + 1
        return self.pass_dir(pass_name) / self.capture_filename(pass_name, index)

    def add_capture(self, pass_name: str, payload: Dict[str, Any]) -> CaptureRecord:
        """Record a capture that has already been written to disk.

        The index is assigned here, never by the caller, so the manifest order
        and the filename numbering can never disagree.
        """
        index = self.capture_count(pass_name) + 1
        record = CaptureRecord(index, self.capture_filename(pass_name, index), payload)
        self._captures[pass_name].append(record)
        return record

    def captures(self, pass_name: str) -> List[Dict[str, Any]]:
        return [record.as_dict() for record in self._captures[pass_name]]

    # -- manifests ---------------------------------------------------------

    def _manifest(self, pass_name: str) -> Dict[str, Any]:
        return {
            "session_type": self._passes[pass_name].session_type,
            "session_id": self.session_id,
            "study_instance_uid": self.study_uid,
            "eagle_eye_version": self.version,
            "created_at": self.created_at,
            "layout": self._layout,
            "capture_order": self._pass_geometry.get(pass_name, {}),
            "capture_count": self.capture_count(pass_name),
            "captures": self.captures(pass_name),
        }

    def _session_document(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "eagle_eye_version": self.version,
            "session_id": self.session_id,
            "session_kind": self.protocol_id,
            "created_at": self.created_at,
            "completed_at": self._completed_at,
            "study_instance_uid": self.study_uid,
            "layout": self._layout,
            "series_selection": self._selection,
            "passes": {
                name: {
                    "directory": self._passes[name].directory,
                    "manifest": f"{self._passes[name].directory}/{MANIFEST_JSON}",
                    "capture_count": self.capture_count(name),
                    "capture_order": self._pass_geometry.get(name, {}),
                }
                for name in self._pass_order
            },
            "notes": list(self._notes),
        }
        doc.update(self._study_context)
        return doc

    def write(self, completed: bool = True) -> Path:
        """Write session.json and both manifests. Returns the session folder."""
        self.ensure_dirs()
        if completed and not self._completed_at:
            self._completed_at = _utc_now_iso()
        for name in self._pass_order:
            _write_json(self.pass_dir(name) / MANIFEST_JSON, self._manifest(name))
        if self._series_sources:
            _write_json(
                self.path / LOCAL_SERIES_SOURCES_JSON,
                {
                    "schema_version": "1.0.0",
                    "series": self._series_sources,
                },
            )
        _write_json(self.path / SESSION_JSON, self._session_document())
        return self.path

    # -- validation --------------------------------------------------------

    def validate(self) -> List[str]:
        """Cross-check disk against the manifests (spec 19).

        Returns a list of problems - empty means the session is internally
        consistent: every manifest entry has a file, every file has a manifest
        entry, indices are 1..N with no gaps or duplicates.
        """
        problems: List[str] = []
        for name in self._pass_order:
            records = self._captures[name]
            directory = self.pass_dir(name)

            expected = [record.image for record in records]
            indices = [record.index for record in records]
            if indices != list(range(1, len(records) + 1)):
                problems.append(f"{name}: capture indices are not a gapless 1..N sequence: {indices}")

            if len(set(expected)) != len(expected):
                problems.append(f"{name}: duplicate capture filenames in the manifest")

            for filename in expected:
                if not (directory / filename).is_file():
                    problems.append(f"{name}: manifest lists {filename} but the file is missing")

            try:
                on_disk = sorted(p.name for p in directory.glob("*.png"))
            except OSError:
                on_disk = []
            orphans = sorted(set(on_disk) - set(expected))
            if orphans:
                problems.append(f"{name}: {len(orphans)} image(s) on disk are not in the manifest: {orphans[:5]}")

        return problems


def _write_json(path: Path, document: Dict[str, Any]) -> None:
    """Atomic-ish JSON write: temp file then replace, so a crash mid-write
    can never leave a half-parsed manifest behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, default=str)
    os.replace(str(tmp), str(path))


def create_session(
    study_uid: str,
    root: Optional[Path] = None,
    session_id: Optional[str] = None,
    now: Optional[datetime] = None,
    passes: Optional[Sequence[PassSpec]] = None,
    protocol_id: str = "lumbar_mri",
) -> EagleEyeCaptureSession:
    """Create (and make on disk) a new session folder for one study."""
    base = Path(root) if root is not None else default_session_root()
    sid = session_id or _session_id(now)
    path = base / _safe_segment(study_uid, "unknown_study") / _safe_segment(sid, "session")

    # A same-second re-run must not silently append to the previous session.
    if path.exists():
        suffix = 2
        while (base / _safe_segment(study_uid, "unknown_study") / f"{sid}_{suffix}").exists():
            suffix += 1
        sid = f"{sid}_{suffix}"
        path = base / _safe_segment(study_uid, "unknown_study") / sid

    session = EagleEyeCaptureSession(
        path, study_uid, sid, _utc_now_iso(now),
        passes=passes, protocol_id=protocol_id,
    )
    session.ensure_dirs()
    return session


def save_pixmap(pixmap: Any, path: Path) -> bool:
    """Write a QPixmap to ``path`` as PNG. Returns True on success.

    Kept here so the capture controller has one place to change if the image
    format ever moves, but it is the ONLY Qt-touching function in this module
    and it is never called by the pure-python tests.
    """
    try:
        if pixmap is None or pixmap.isNull():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        return bool(pixmap.save(str(path), "PNG"))
    except Exception as exc:
        logger.error("eagle_eye_lumbar: failed to save capture %s: %s", path, exc)
        return False


# Historical name, kept so existing callers and guards keep working.
LumbarCaptureSession = EagleEyeCaptureSession
