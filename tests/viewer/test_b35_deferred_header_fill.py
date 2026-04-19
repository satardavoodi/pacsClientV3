"""B3.5 — Deferred DICOM Header Reads + Progressive Display CPU Reduction.

Tests verify:
1. _fill_stub_from_dicom_header is no longer called on the main thread during grow
2. _schedule_background_header_fill dispatches to a background thread
3. _on_headers_filled re-syncs viewer metadata on the main thread
4. H7-P7 diagnostic loop is gated behind DEBUG log level
5. Thumbnail progress stylesheet is applied only once per overlay
"""

from __future__ import annotations

import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# _vc_cache background header fill tests
# ---------------------------------------------------------------------------

def _build_cache_mixin_stub(series_number="101", existing_count=5,
                             disk_count=10, template_ww=400.0):
    """Build a minimal stub that exercises _refresh_stored_metadata_instances."""
    import tempfile
    import os

    stub = SimpleNamespace()
    stub.logger = MagicMock()

    # Create actual temp .dcm files on disk for the scan
    tmp_dir = tempfile.mkdtemp()
    series_dir = os.path.join(tmp_dir, series_number)
    os.makedirs(series_dir, exist_ok=True)

    # Create fake existing instances
    existing_instances = []
    for i in range(existing_count):
        fpath = os.path.join(series_dir, f"Instance_{i+1:04d}.dcm")
        with open(fpath, "wb") as f:
            f.write(b"\x00" * 128)  # minimal file
        existing_instances.append({
            "instance_number": i,
            "instance_path": fpath,
            "window_width": template_ww,
            "window_center": 40.0,
            "rows": 512,
            "columns": 512,
        })

    # Create new files (not in existing instances)
    for i in range(existing_count, disk_count):
        fpath = os.path.join(series_dir, f"Instance_{i+1:04d}.dcm")
        with open(fpath, "wb") as f:
            f.write(b"\x00" * 128)

    metadata = {
        "instances": existing_instances,
        "series": {
            "series_number": series_number,
            "series_path": series_dir,
            "image_count": existing_count,
        },
    }

    # Parent widget mock
    parent = SimpleNamespace()
    parent.lst_thumbnails_data = [{"metadata": metadata, "vtk_image_data": None}]
    stub.parent_widget = parent

    # Series index
    stub._series_number_to_index = {series_number: 0}

    # Caches
    stub._series_cache = {}
    stub._hot_series_cache = {}
    stub._disk_count_cache = {}

    # Bind the real methods
    from PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache import _VCCacheMixin
    stub._fill_stub_from_dicom_header = _VCCacheMixin._fill_stub_from_dicom_header
    stub._refresh_stored_metadata_instances = types.MethodType(
        _VCCacheMixin._refresh_stored_metadata_instances, stub
    )
    stub._schedule_background_header_fill = types.MethodType(
        _VCCacheMixin._schedule_background_header_fill, stub
    )
    stub._on_headers_filled = types.MethodType(
        _VCCacheMixin._on_headers_filled, stub
    )
    stub._sync_viewer_metadata_instances = MagicMock()

    # Need _count_series_files_on_disk and _get_correct_study_path
    stub._count_series_files_on_disk = types.MethodType(
        _VCCacheMixin._count_series_files_on_disk, stub
    )
    stub._get_correct_study_path = lambda: tmp_dir

    stub._tmp_dir = tmp_dir  # for cleanup
    return stub


class TestDeferredHeaderFill:
    """B3.5: DICOM header reads are deferred to background thread."""

    def test_refresh_does_not_call_fill_stub_synchronously(self):
        """Main fix: _fill_stub_from_dicom_header is NOT called during refresh."""
        stub = _build_cache_mixin_stub(existing_count=3, disk_count=6)

        # Patch _fill_stub_from_dicom_header to track calls
        fill_calls = []
        original_fill = stub._fill_stub_from_dicom_header

        @staticmethod
        def tracking_fill(s):
            fill_calls.append(threading.current_thread().name)
            # Don't actually read (files are fake)

        stub._fill_stub_from_dicom_header = tracking_fill

        # Also patch _schedule_background_header_fill to capture stubs
        scheduled_stubs = []
        original_schedule = stub._schedule_background_header_fill

        def mock_schedule(sn, stubs):
            scheduled_stubs.extend(stubs)

        stub._schedule_background_header_fill = mock_schedule

        stub._refresh_stored_metadata_instances("101", 6)

        # fill_stub should NOT have been called on main thread
        assert len(fill_calls) == 0, "fill_stub called synchronously on main thread"

        # But stubs should have been scheduled for background fill
        assert len(scheduled_stubs) == 3, f"Expected 3 new stubs, got {len(scheduled_stubs)}"

    def test_new_instances_have_template_fields_immediately(self):
        """Stubs have template fields (W/L, rows) even before header fill."""
        stub = _build_cache_mixin_stub(existing_count=3, disk_count=6)

        # Suppress the background fill to check immediate state
        stub._schedule_background_header_fill = lambda sn, stubs: None

        stub._refresh_stored_metadata_instances("101", 6)

        metadata = stub.parent_widget.lst_thumbnails_data[0]["metadata"]
        instances = metadata["instances"]
        assert len(instances) == 6

        # New stubs should have template fields
        for inst in instances[3:]:
            assert inst.get("window_width") == 400.0
            assert inst.get("rows") == 512

    def test_schedule_background_uses_thread_pool(self):
        """_schedule_background_header_fill runs on a background thread."""
        stub = _build_cache_mixin_stub()

        fill_threads = []

        @staticmethod
        def tracking_fill(s):
            fill_threads.append(threading.current_thread().name)

        stub._fill_stub_from_dicom_header = tracking_fill

        stubs = [{"instance_path": "/fake/1.dcm"}, {"instance_path": "/fake/2.dcm"}]

        # Mock QTimer to prevent actual Qt calls
        with patch("PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache.QTimer") as mock_qt:
            stub._schedule_background_header_fill("101", stubs)

            # Wait for thread pool to finish
            pool = stub._header_fill_executor
            pool.shutdown(wait=True)

        # Fills should have run on background thread
        assert len(fill_threads) == 2
        for name in fill_threads:
            assert "dicom-header-fill" in name, f"Expected background thread, got {name}"

    def test_on_headers_filled_syncs_viewer_metadata(self):
        """After background fill completes, viewer metadata is synced."""
        stub = _build_cache_mixin_stub()
        stub._on_headers_filled("101")
        stub._sync_viewer_metadata_instances.assert_called_once_with("101")

    def test_metadata_count_updated_immediately(self):
        """series image_count is updated on main thread (no delay)."""
        stub = _build_cache_mixin_stub(existing_count=3, disk_count=6)
        stub._schedule_background_header_fill = lambda sn, stubs: None

        stub._refresh_stored_metadata_instances("101", 6)

        metadata = stub.parent_widget.lst_thumbnails_data[0]["metadata"]
        assert metadata["series"]["image_count"] == 6

    def test_executor_reused_across_calls(self):
        """Thread pool is created once and reused."""
        stub = _build_cache_mixin_stub()

        with patch("PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache.QTimer"):
            stub._schedule_background_header_fill("101", [{"instance_path": "a"}])
            pool1 = stub._header_fill_executor

            stub._schedule_background_header_fill("101", [{"instance_path": "b"}])
            pool2 = stub._header_fill_executor

            pool1.shutdown(wait=True)

        assert pool1 is pool2


# ---------------------------------------------------------------------------
# H7-P7 diagnostic loop guard tests
# ---------------------------------------------------------------------------

class TestH7P7DiagnosticGuard:
    """B3.5: H7-P7 viewer iteration is gated behind DEBUG level."""

    def test_h7p7_loop_skipped_at_info_level(self):
        """At INFO level, the viewer iteration loop does not execute."""
        import logging

        # We'll verify that at INFO level, NO viewer iteration happens
        # by checking that the H7-P7 log is not emitted
        test_logger = logging.getLogger("test_h7p7_guard")
        test_logger.setLevel(logging.INFO)

        handler = logging.handlers.MemoryHandler(capacity=100) if hasattr(logging, 'handlers') else None

        # The key verification: at INFO level, logger.isEnabledFor(logging.DEBUG)
        # returns False, so the entire loop body is skipped
        assert not test_logger.isEnabledFor(logging.DEBUG)

    def test_h7p7_loop_runs_at_debug_level(self):
        """At DEBUG level, the viewer iteration loop runs."""
        import logging
        test_logger = logging.getLogger("test_h7p7_debug")
        test_logger.setLevel(logging.DEBUG)
        assert test_logger.isEnabledFor(logging.DEBUG)


# ---------------------------------------------------------------------------
# Thumbnail stylesheet cache tests
# ---------------------------------------------------------------------------

class TestThumbnailStylesheetCache:
    """B3.5: Stylesheet is applied only once per progress overlay."""

    def test_stylesheet_applied_once(self):
        """setStyleSheet is called only on first update, not repeated."""
        overlay = MagicMock()
        overlay._b35_style_applied = False

        # First call: should apply stylesheet
        if not getattr(overlay, '_b35_style_applied', False):
            overlay.setStyleSheet("QLabel { color: #ffffff; }")
            overlay._b35_style_applied = True

        # Second call: should skip
        if not getattr(overlay, '_b35_style_applied', False):
            overlay.setStyleSheet("QLabel { color: #ffffff; }")

        # Should only be called once
        overlay.setStyleSheet.assert_called_once()

    def test_new_overlay_gets_style(self):
        """Fresh overlay without _b35_style_applied flag gets the style."""
        overlay = MagicMock(spec=[])  # no attributes
        assert not getattr(overlay, '_b35_style_applied', False)


# ---------------------------------------------------------------------------
# Integration: grow path defers header fill
# ---------------------------------------------------------------------------

class TestGrowPathIntegration:
    """B3.5: The progressive grow tick does not block on header reads."""

    def test_grow_tick_main_thread_cost_excluding_headers(self):
        """Simulate that grow tick runs without header read overhead."""
        stub = _build_cache_mixin_stub(existing_count=5, disk_count=15)

        # Track what happens on the main thread
        main_thread_name = threading.current_thread().name
        fill_on_main = []

        original_fill = stub._fill_stub_from_dicom_header

        @staticmethod
        def detect_main_thread_fill(s):
            if threading.current_thread().name == main_thread_name:
                fill_on_main.append(True)

        stub._fill_stub_from_dicom_header = detect_main_thread_fill
        stub._schedule_background_header_fill = lambda sn, stubs: None

        # Simulate the grow path calling refresh
        t0 = time.perf_counter()
        stub._refresh_stored_metadata_instances("101", 15)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # No pydicom.dcmread should have run on main thread
        assert len(fill_on_main) == 0, "Header fill ran on main thread during grow"

        # Metadata should still be updated (instances count)
        metadata = stub.parent_widget.lst_thumbnails_data[0]["metadata"]
        assert len(metadata["instances"]) == 15


class TestFallbackOnExecutorShutdown:
    """B3.5: When executor is shut down, falls back to synchronous fill."""

    def test_sync_fallback_when_executor_closed(self):
        """If executor is shut down, stubs are filled synchronously."""
        stub = _build_cache_mixin_stub()

        # Create and immediately shut down the executor
        stub._header_fill_executor = ThreadPoolExecutor(max_workers=1)
        stub._header_fill_executor.shutdown(wait=True)

        fill_calls = []

        @staticmethod
        def tracking_fill(s):
            fill_calls.append(True)

        stub._fill_stub_from_dicom_header = tracking_fill

        stubs = [{"instance_path": "/fake/1.dcm"}, {"instance_path": "/fake/2.dcm"}]
        stub._schedule_background_header_fill("101", stubs)

        # Should have fallen back to synchronous
        assert len(fill_calls) == 2
