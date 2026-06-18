"""Guard: Main Page and Patient Viewer thumbnails share the unified pipeline (2026-06-17).

Architecture verification (per the thumbnail-pipeline bug/architecture check): the
home-page right panel and the opened patient-viewer sidebar must both resolve series
thumbnails through the SAME unified store/service — the shared `ThumbnailStore`
singleton (memory, keyed (study_uid, series_number)) + canonical disk cache
(THUMBNAIL_PATH/<study_uid>/<series_number>.png) + `ThumbnailImageSourceService` —
and the viewer must REUSE the cache (no separate legacy fetch path, no regeneration,
no needless re-query). This is a pure source scan (no app import; runs anywhere).

As-built: docs/pipelines/thumbnail-pipeline.md.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="ignore")


_PANELS = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py")
_THUMBS = _read("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py")
_SRC_SVC = _read("PacsClient/pacs/patient_tab/utils/thumbnail_image_source_service.py")
_HP = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py")


def test_viewer_sidebar_uses_unified_source_service():
    # The live sidebar widget builder resolves images via ThumbnailImageSourceService,
    # not a private QPixmap(file) / DICOM-regeneration path.
    assert "ThumbnailImageSourceService" in _PANELS
    assert "load_pixmap(" in _PANELS


def test_source_service_reads_shared_store_then_disk():
    # The shared read helper is memory(store)-first then disk — the same store the
    # home page uses (ThumbnailStore singleton).
    assert "ThumbnailStore.instance()" in _SRC_SVC
    assert "get_bytes(" in _SRC_SVC


def test_viewer_reuses_cache_before_any_server_fetch():
    # On open, the viewer checks the local cache and renders it directly; the server
    # fetch (get_study_thumbnails) appears AFTER the cache-hit early return.
    assert "check_and_get_thumbnails(" in _THUMBS
    hit = _THUMBS.index("ThumbnailReusedFromUnifiedPipeline")
    fetch = _THUMBS.index("get_study_thumbnails(")
    assert hit < fetch, "cache reuse must come before the server fetch"


def test_viewer_lifecycle_logging_present():
    for ev in (
        "PatientViewerThumbnailRequested",
        "ThumbnailCacheHit",
        "ThumbnailCacheMiss",
        "ThumbnailReusedFromUnifiedPipeline",
        "ThumbnailFetchedFromServer",
    ):
        assert ev in _THUMBS, f"viewer thumbnail log {ev!r} missing"


def test_source_service_memory_vs_disk_logging_present():
    assert "ThumbnailLoadedFromMemory" in _SRC_SVC
    assert "ThumbnailLoadedFromDisk" in _SRC_SVC


def test_main_page_logging_present():
    for ev in ("MainPageThumbnailRequested", "ThumbnailCacheHit", "ThumbnailCacheMiss"):
        assert ev in _HP, f"main-page thumbnail log {ev!r} missing"


def test_no_base_path_in_source_service():
    # Guardrail from the pipeline doc: the unified read service resolves through
    # ThumbnailStore (→ THUMBNAIL_PATH under USER_DATA_ROOT), never the BASE_PATH
    # (code root) legacy location.
    assert "BASE_PATH" not in _SRC_SVC
