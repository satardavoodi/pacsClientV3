"""Guard: the patient-open path prefers the per-server SOURCE_PATH for a SERVER
study when the DB-stored study_path is stale (2026-06-24, mehr 15436 / 14965).

Root cause this pins: under a per-server profile (mehr) the downloader writes to
SOURCE_PATH (user_data/servers/<id>/patients/dicom), but the DB study_path can be
stale — left at the pre-per-server SHARED location (user_data/patients/dicom). The
viewer then scanned a dead folder (live log: `path_scan candidates=0 matches=0`),
judged the series "not downloaded", and looped re-downloading forever while the
files sat under SOURCE_PATH. The open path now prefers `SOURCE_PATH/<study_uid>`
for a server study when the DB path diverges AND is missing/empty on disk.

Pure source-pin (the open path is a large async GUI method; this avoids the
home_panel circular-import collection issue and needs no PySide6).
"""
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _open_src() -> str:
    return (
        _repo_root()
        / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel"
        / "_hp_patient_open.py"
    ).read_text(encoding="utf-8")


def test_sourcepath_guard_present_and_flagged():
    src = _open_src()
    assert "AIPACS_OPEN_SOURCEPATH_GUARD" in src
    # Falls back to the canonical per-server location.
    assert "SOURCE_PATH / study_uid" in src
    # Emits an observable trace when it corrects a stale path.
    assert "study_path_sourcepath_guard" in src


def test_guard_scoped_to_server_studies_only():
    """The guard must NOT touch local / offline-cloud studies (their study_path is
    authoritative)."""
    src = _open_src()
    idx = src.find("study_path_sourcepath_guard")
    assert idx != -1
    # The branch that contains the guard is gated on a non-local, non-offline study.
    # (The explanatory comment is long, so look well back from the marker.)
    head = src[max(0, idx - 2400): idx]
    assert "not is_local" in head
    assert "not is_offline_cloud" in head


def test_guard_only_overrides_when_db_path_not_live():
    """The override must be conditioned on the DB path being missing/empty
    (os.path.isdir + os.listdir), so a live DB path is preserved."""
    src = _open_src()
    idx = src.find("study_path_sourcepath_guard")
    head = src[max(0, idx - 600): idx + 200]
    assert "_db_live" in head
    assert "os.path.isdir" in head
    assert "os.listdir" in head
