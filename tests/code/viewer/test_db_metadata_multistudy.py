"""Guard for B4 — per-series DB-first metadata for multi-study (2026-06-21, staged default-off).

Multi-study series re-scanned every DICOM header off disk on each load because the
legacy guard (_ensure_study_pk_for_db_metadata) fed the PRIMARY study_pk, which is
wrong for an offset-key (non-primary) series. B4 resolves the series' OWN study_pk
(from its entry's study_uid) and passes it to load_single_series_by_number so geometry
comes from dicom.db. Safety: the existing "auto" self-verify keeps a per-study_pk trust
cache and falls back to disk on any geometry mismatch — so a wrong/incomplete DB
geometry for any study can never reach the viewport.

Source-pin (the load path needs a live DB + DICOM to exercise), matching the style of
test_drag_loads_exact_series.py / test_first_image_prime.py.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SRC = (
    _REPO / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py"
).read_text(encoding="utf-8")
_IMG = (
    _REPO / "PacsClient/pacs/patient_tab/utils/image_io.py"
).read_text(encoding="utf-8")


def test_multistudy_dbmeta_flag_default_off():
    # Staged: production keeps the unchanged disk-header path until
    # AIPACS_VIEWER_DB_METADATA_MULTISTUDY=1 is set and live-validated.
    assert 'AIPACS_VIEWER_DB_METADATA_MULTISTUDY", "0"' in _SRC


def test_per_series_study_pk_resolved_and_used():
    # The series' OWN study_uid is captured during resolution, its study_pk resolved,
    # and passed to the loader as the effective study_pk (NOT the primary's).
    assert "_ms_study_uid = str((_ms_entry or {}).get('study_uid')" in _SRC
    assert "find_study_pk_with_study_uid(_ms_study_uid)" in _SRC
    assert "_effective_study_pk = _ms_spk" in _SRC
    assert "study_pk=_effective_study_pk" in _SRC


def test_gated_by_existing_db_metadata_mode():
    # Only engages when the base DB-metadata mode is active (auto/verify/1/on/true),
    # so AIPACS_VIEWER_DB_METADATA=0 still disables everything (global rollback).
    assert 'AIPACS_VIEWER_DB_METADATA", "auto"' in _SRC
    assert '_dbm in ("1", "verify", "auto", "on", "true")' in _SRC


def test_autoverify_is_per_study_pk_failsafe():
    # Geometry safety net (in load_single_series_by_number): the DB-geometry trust
    # cache is keyed by study_pk and a mismatch falls back to disk — so per-series
    # study_pk means each study self-verifies its OWN geometry.
    assert "_db_geom_trust_cache[study_pk]" in _IMG
    assert "geometry_match=False" in _IMG


def test_per_widget_study_pk_cache_present():
    # Avoid a DB lookup per series — cache study_uid->study_pk on the widget.
    assert "_ms_study_pk_cache" in _SRC
