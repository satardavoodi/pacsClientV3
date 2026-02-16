"""Preview Engine — lightweight first-slice previews for Mode B.

During active downloads (Mode B), ZetaBoost warmup is blocked because its
ITK filter pipeline holds the GIL for 3-12 s per series, freezing the UI.

Instead, the preview engine loads **only the first DICOM slice** of each
downloaded series, converts it to a VTK image **without** ITK filters, and
caches the result.  This gives the viewer instant visual feedback for
drag-drop during downloads with negligible CPU cost.

Design constraints
------------------
- Each preview load takes <200 ms (single slice, no filters).
- NO ITK filter application — raw pixel values are sufficient for preview.
- Thread-safe cache: any thread can read; only one thread loads per series.
- Previews are discarded when the orchestrator transitions to POST_DOWNLOAD
  (ZetaBoost will load full volumes with filters at that point).
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional, Tuple, Any


class PreviewEngine:
    """Instant single-slice preview cache for concurrent-download mode."""

    def __init__(self, logger=None):
        self._cache: Dict[str, Tuple[Any, dict]] = {}  # series -> (vtk_data, metadata)
        self._loading: set = set()
        self._lock = threading.Lock()
        self._logger = logger

    # ------------------------------------------------------------------- API
    def load_preview(
        self,
        series_number,
        study_path: str,
        *,
        patient_pk=None,
        study_pk=None,
        ordering_by_instances_number: bool = True,
    ) -> Optional[Tuple[Any, dict]]:
        """Load a 1-slice preview.  Safe to call from any thread.

        Returns ``(vtk_image_data, metadata)`` or ``None`` on failure.
        Uses file-system access only (no network, no DB beyond what
        ``load_series_preview`` does internally).
        """
        key = str(series_number)

        # Fast cache check
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            # Dedup: only one thread loads a given series.
            if key in self._loading:
                return None
            self._loading.add(key)

        try:
            from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview

            result = load_series_preview(
                study_path=study_path,
                series_number=int(series_number),
                patient_pk=patient_pk,
                study_pk=study_pk,
                max_files=1,
            )
            if result is not None:
                vtk_data, metadata = result[0], result[1]
                if vtk_data is not None and isinstance(metadata, dict):
                    # Tag as preview so the cache validator won't treat it
                    # as a full-volume entry.
                    metadata["preview_only"] = True
                    with self._lock:
                        self._cache[key] = (vtk_data, metadata)
                    return (vtk_data, metadata)
        except Exception as exc:
            try:
                print(f"[PreviewEngine] series={key} load failed: {exc}")
            except Exception:
                pass
        finally:
            with self._lock:
                self._loading.discard(key)

        return None

    def get_preview(self, series_number) -> Optional[Tuple[Any, dict]]:
        """Instant O(1) cache lookup — no I/O."""
        with self._lock:
            return self._cache.get(str(series_number))

    def has_preview(self, series_number) -> bool:
        with self._lock:
            return str(series_number) in self._cache

    def clear(self):
        """Discard all previews (e.g. on transition to POST_DOWNLOAD)."""
        with self._lock:
            self._cache.clear()
            self._loading.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
