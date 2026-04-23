"""
modules.printing.data.dicom_enrichment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Returns series-info enriched with on-disk file counts and thumbnails.
Falls back to plain DB data when enrichment fails.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def get_series_with_enrichment(study_uid: str) -> List[dict]:
    """Return series list enriched with on-disk file counts.

    Delegates to :func:`series_repository.get_series_for_study` and then
    augments each record with a live ``image_count`` from the filesystem so
    the printing UI shows the actual number of available slices rather than
    whatever the server originally reported.
    """
    from .series_repository import get_series_for_study

    series = get_series_for_study(study_uid)
    for item in series:
        series_path = item.get("series_path")
        if series_path:
            try:
                p = Path(series_path)
                if p.is_dir():
                    dcm_count = sum(
                        1
                        for f in p.iterdir()
                        if f.suffix.lower() in (".dcm", "") and f.is_file()
                    )
                    if dcm_count > 0:
                        item["image_count"] = dcm_count
            except Exception as exc:
                logger.debug("[printing.data.enrichment] disk count failed: %s", exc)
    return series
