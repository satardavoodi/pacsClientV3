from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PacsClient.pacs.patient_tab.utils.thumbnail_metadata_service import ThumbnailMetadataService


class ThumbnailProjectionService:
    """Build sidebar thumbnail payloads from normalized metadata sources."""

    def __init__(self, metadata_service: ThumbnailMetadataService | None = None):
        self.metadata_service = metadata_service or ThumbnailMetadataService()

    @staticmethod
    def create_standard_metadata(
        series_number,
        modality: str = "Unknown",
        series_description: str = "",
        image_count: int = 1,
        protocol_name: str = "",
        body_part_examined: str = "",
        is_downloading: bool = False,
        main_thumbnail: bool = True,
    ) -> dict:
        return {
            "series": {
                "series_number": series_number,
                "modality": modality,
                "series_description": series_description,
                "protocol_name": protocol_name,
                "body_part_examined": body_part_examined,
                "main_thumbnail": main_thumbnail,
            },
            "instances": [{"dummy": "data"}] * max(0, int(image_count or 0)),
            "is_downloading": is_downloading,
        }

    @staticmethod
    def build_series_info_from_series_metadata(series_metadata: dict, fallback_series_number: str) -> dict:
        series_number = series_metadata.get("series_number", fallback_series_number)
        return {
            "series": {
                "series_uid": series_metadata.get("series_uid", ""),
                "series_number": series_number,
                "modality": series_metadata.get("modality", "Unknown"),
                "series_description": series_metadata.get("series_description", ""),
                "protocol_name": series_metadata.get("protocol_name", ""),
                "body_part_examined": series_metadata.get("body_part_examined", ""),
                "manufacturer": series_metadata.get("manufacturer", ""),
                "institution_name": series_metadata.get("institution_name", ""),
            },
            "series_uid": series_metadata.get("series_uid", ""),
            "series_number": series_number,
            "image_count": series_metadata.get("image_count", 0),
        }

    def build_series_info_from_loaded_metadata(self, metadata: dict, fallback_series_number: str) -> dict:
        series_meta = metadata.get("series", {}) if isinstance(metadata, dict) else {}
        series_metadata = {
            "series_uid": series_meta.get("series_uid", ""),
            "series_number": series_meta.get("series_number", fallback_series_number),
            "modality": series_meta.get("modality", "Unknown"),
            "series_description": series_meta.get("series_description", ""),
            "protocol_name": series_meta.get("protocol_name", ""),
            "body_part_examined": series_meta.get("body_part_examined", ""),
            "manufacturer": series_meta.get("manufacturer", ""),
            "institution_name": series_meta.get("institution_name", ""),
            "image_count": len(metadata.get("instances", [])) if isinstance(metadata, dict) else 0,
        }
        return self.build_series_info_from_series_metadata(series_metadata, fallback_series_number)

    def get_cached_series_info(self, parent_widget, series_number: str) -> dict:
        series_metadata = self.metadata_service.get_cached_series_metadata(parent_widget, str(series_number))
        return self.build_series_info_from_series_metadata(series_metadata, str(series_number))

    def get_batch_cached_series_metadata(self, parent_widget, series_numbers: Iterable[str]) -> dict[str, dict]:
        return self.metadata_service.get_batch_cached_series_metadata(parent_widget, series_numbers)

    def build_cached_thumbnail_entries(self, parent_widget, image_files: Iterable[Path]) -> list[dict]:
        files = list(image_files or [])
        series_names = [str(image_file.stem) for image_file in files]
        all_metadata = self.get_batch_cached_series_metadata(parent_widget, series_names)

        entries: list[dict] = []
        for image_file in files:
            series_name = str(image_file.stem)
            series_metadata = all_metadata.get(series_name, {})
            entries.append(
                {
                    "file_path": str(image_file),
                    "series_number": series_metadata.get("series_number", series_name),
                    "modality": series_metadata.get("modality", "Unknown"),
                    "series_description": series_metadata.get("series_description", f"Series {series_name}"),
                    "image_count": series_metadata.get("image_count", 0),
                    "protocol_name": series_metadata.get("protocol_name", ""),
                    "body_part_examined": series_metadata.get("body_part_examined", ""),
                    "series_uid": series_metadata.get("series_uid", ""),
                    "is_cached": True,
                }
            )
        return entries