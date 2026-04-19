from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PacsClient.utils.db_manager import (
    get_series_by_study_and_number,
    get_series_by_study_uid,
)


class SeriesMetadataService:
    """Reusable read-only provider for series summary metadata.

    This service is intentionally framework-light and can be used from Home UI,
    patient-tab UI, and other module code that needs normalized series summary
    records without duplicating DB lookup and fallback shaping logic.
    """

    @staticmethod
    def resolve_study_uid(parent_widget) -> str | None:
        if parent_widget is None:
            return None

        study_uid = str(getattr(parent_widget, "study_uid", "") or "").strip()
        if study_uid:
            return study_uid

        import_folder_path = getattr(parent_widget, "import_folder_path", None)
        if import_folder_path:
            try:
                return Path(import_folder_path).name or None
            except Exception:
                return None
        return None

    @staticmethod
    def normalize_series_metadata(series_data: dict | None, *, fallback_series_number: str) -> dict:
        if not series_data:
            return {
                "series_uid": "",
                "series_number": fallback_series_number,
                "modality": "Unknown",
                "series_description": f"Series {fallback_series_number}",
                "image_count": 0,
                "protocol_name": "",
                "body_part_examined": "",
                "manufacturer": "",
                "institution_name": "",
            }

        return {
            "series_uid": series_data.get("series_uid", ""),
            "series_number": series_data.get("series_number", fallback_series_number),
            "modality": series_data.get("modality", "Unknown"),
            "series_description": series_data.get("series_description", ""),
            "image_count": series_data.get("image_count", 0),
            "protocol_name": series_data.get("protocol_name", ""),
            "body_part_examined": series_data.get("body_part_examined", ""),
            "manufacturer": series_data.get("manufacturer", ""),
            "institution_name": series_data.get("institution_name", ""),
        }

    def get_series_metadata(self, study_uid: str, series_number: str) -> dict:
        if not study_uid:
            return self.normalize_series_metadata(None, fallback_series_number=str(series_number))

        try:
            series_data = get_series_by_study_and_number(study_uid, series_number)
        except Exception:
            series_data = None

        return self.normalize_series_metadata(
            series_data,
            fallback_series_number=str(series_number),
        )

    def get_series_metadata_for_widget(self, parent_widget, series_number: str) -> dict:
        study_uid = self.resolve_study_uid(parent_widget)
        return self.get_series_metadata(study_uid or "", str(series_number))

    def get_series_list(self, study_uid: str) -> list[dict]:
        if not study_uid:
            return []

        try:
            all_series = get_series_by_study_uid(study_uid)
        except Exception:
            all_series = []

        normalized: list[dict] = []
        for series_data in all_series or []:
            series_number = str(series_data.get("series_number", "") or "")
            if not series_number:
                continue
            normalized.append(
                self.normalize_series_metadata(
                    series_data,
                    fallback_series_number=series_number,
                )
            )
        return normalized

    def get_series_list_for_widget(self, parent_widget) -> list[dict]:
        study_uid = self.resolve_study_uid(parent_widget)
        return self.get_series_list(study_uid or "")

    def get_batch_series_metadata(self, study_uid: str, series_numbers: Iterable[str]) -> dict[str, dict]:
        normalized_numbers = [str(sn) for sn in series_numbers or []]
        if not study_uid or not normalized_numbers:
            return {
                series_number: self.normalize_series_metadata(None, fallback_series_number=series_number)
                for series_number in normalized_numbers
            }

        all_series = self.get_series_list(study_uid)
        metadata_map = {
            str(series_data.get("series_number", "")): series_data
            for series_data in all_series
            if str(series_data.get("series_number", ""))
        }

        for series_number in normalized_numbers:
            metadata_map.setdefault(
                series_number,
                self.normalize_series_metadata(None, fallback_series_number=series_number),
            )
        return metadata_map

    def get_batch_series_metadata_for_widget(self, parent_widget, series_numbers: Iterable[str]) -> dict[str, dict]:
        study_uid = self.resolve_study_uid(parent_widget)
        return self.get_batch_series_metadata(study_uid or "", series_numbers)