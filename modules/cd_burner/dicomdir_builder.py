"""DICOMDIR builder — compatibility shim.

The implementation moved to the CORE module ``modules/dicom_media/dicomdir.py``
so that BOTH media workflows share ONE implementation (no fork):

* the CD burner (this optional ``run_cd`` plugin), and
* Offline Sync export (core ``PacsClient/utils/offline_cloud.py``), which cannot
  import from ``modules.cd_burner`` because that package is excluded from the
  engine and only ships inside the optional plugin payload.

Everything below is re-exported unchanged, so every existing import
(``from .dicomdir_builder import DicomDirBuilder, check_pydicom_available``,
``_ensure_dicomdir_fields``) keeps working byte-for-byte.
"""

from modules.dicom_media.dicomdir import (  # noqa: F401
    PYDICOM_AVAILABLE,
    DicomDirBuilder,
    _DICOMDIR_REQUIRED_FIELDS,
    _ensure_dicomdir_fields,
    _first_value,
    _is_blank,
    check_pydicom_available,
)

__all__ = [
    "DicomDirBuilder",
    "check_pydicom_available",
    "PYDICOM_AVAILABLE",
    "_ensure_dicomdir_fields",
]
