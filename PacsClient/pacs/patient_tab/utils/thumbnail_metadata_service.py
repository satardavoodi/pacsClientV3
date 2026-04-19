from __future__ import annotations

from PacsClient.utils.series_metadata_service import SeriesMetadataService


class ThumbnailMetadataService(SeriesMetadataService):
    """Backward-compatible alias for thumbnail/sidebar metadata lookups.

    Kept as a stable name for existing patient-tab code, but now backed by the
    project-wide `SeriesMetadataService` so Home UI and other modules can share
    the same normalization and DB access rules without duplication.
    """

    def get_cached_series_metadata(self, parent_widget, series_number: str) -> dict:
        return self.get_series_metadata_for_widget(parent_widget, series_number)

    def get_batch_cached_series_metadata(self, parent_widget, series_numbers) -> dict[str, dict]:
        return self.get_batch_series_metadata_for_widget(parent_widget, series_numbers)
