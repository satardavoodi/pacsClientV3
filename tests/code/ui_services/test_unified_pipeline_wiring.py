"""Source-wiring guard for the unified patient-study-set pipeline (2026-06-17).

Fails if the shared authority, the feature flags, the caller routing, or the legacy
kill-switch tail are removed — i.e. catches a stale build or an accidental revert of the
46630 fix. Pure source scan: no imports of the app, so it runs anywhere (no PySide6).

As-built: docs/pipelines/unified-patient-study-pipeline.md
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="ignore")


def test_shared_authority_present():
    pss = _read("PacsClient/utils/patient_study_set.py")
    for token in (
        "def merge_study_uids",
        "def diff_study_uids",
        "def resolve_study_uids",
        "def build_download_payload",
        "class PatientStudySetService",
    ):
        assert token in pss, f"patient_study_set.py missing {token!r}"
    # The DM queue reads 'study_description'; the shared payload builder must emit it.
    assert "study_description" in pss


def test_open_path_wiring():
    op = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py")
    # Flags (with their env names) present.
    assert "_PSS_MERGE_RESOLVE" in op and "AIPACS_PSS_MERGE_RESOLVE" in op
    assert "_OPEN_TAB_LATE_DOWNLOAD" in op and "AIPACS_OPEN_TAB_LATE_DOWNLOAD" in op
    # Back-fill + late-download methods present.
    assert "def _backfill_open_viewer_studyset" in op
    assert "def _enqueue_missing_series_for_open_study" in op
    # Resolver tail routes through the shared authority...
    assert "merge_study_uids" in op
    # ...and the legacy kill-switch tail (AIPACS_PSS_MERGE_RESOLVE=0) is preserved.
    assert "study_uid_cross_patient_dropped" in op


def test_series_path_wiring():
    sp = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py")
    assert "_OPEN_TAB_BACKFILL" in sp and "AIPACS_OPEN_TAB_STUDYSET_BACKFILL" in sp
    assert "_PSS_SHADOW" in sp
    assert "_backfill_open_viewer_studyset" in sp  # back-fill is invoked from the reconcile path
    assert "build_download_payload" in sp          # enqueue uses the shared payload builder


def test_viewer_canonical_identity_fallback():
    vc = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py")
    assert "_resolve_canonical_series_identity" in vc
    assert "series_instance_uid" in vc  # series_uid -> series_instance_uid fallback present
