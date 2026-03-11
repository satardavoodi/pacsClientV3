"""
ZetaBoost module

Per-patient-tab acceleration layer for:
- serialized one-by-one series processing
- full-series in-memory cache
- strict active-tab-only lifecycle
- Mode B: Image Slice Booster for ±20 slice window caching
"""

from .engine import ZetaBoostEngine, set_global_download_active
from .disk_cache import ZetaBoostDiskCache
from .image_slice_booster import ImageSliceBooster

__all__ = ["ZetaBoostEngine", "ZetaBoostDiskCache", "ImageSliceBooster", "set_global_download_active"]
