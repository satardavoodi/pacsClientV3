"""Content-aware quality checks for derived medical evidence images."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class EvidenceQuality:
    """Small, privacy-safe quality summary with no source pixel payload."""

    width: int
    height: int
    p01: float
    p99: float
    unique_levels: int

    @property
    def pixel_count(self) -> int:
        return int(self.width * self.height)

    @property
    def usable(self) -> bool:
        return (
            self.width >= 64
            and self.height >= 64
            and self.unique_levels >= 8
            and self.p99 - self.p01 >= 4.0
        )


def inspect_image_quality(path: str | Path) -> EvidenceQuality:
    """Reject empty/uniform renders while allowing legitimately dark MRI."""
    try:
        with Image.open(Path(path)) as opened:
            grayscale = np.asarray(opened.convert("L"), dtype=np.uint8)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("The derived evidence image cannot be decoded.") from exc
    if grayscale.ndim != 2 or grayscale.size == 0:
        raise ValueError("The derived evidence image has no pixels.")
    flat = grayscale.reshape(-1)
    stride = max(1, int(np.ceil(flat.size / 500_000)))
    sample = flat[::stride]
    p01, p99 = np.percentile(sample, (1.0, 99.0))
    quality = EvidenceQuality(
        width=int(grayscale.shape[1]),
        height=int(grayscale.shape[0]),
        p01=float(p01),
        p99=float(p99),
        unique_levels=int(np.unique(sample).size),
    )
    if not quality.usable:
        raise ValueError("The derived evidence image is empty or effectively uniform.")
    return quality
