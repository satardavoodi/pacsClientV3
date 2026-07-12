"""Shared DICOM interchange-media helpers (DICOMDIR).

CORE module (always shipped) so BOTH the optional CD burner plugin and the core
Offline Sync export can build a standards-compliant DICOMDIR from the SAME
implementation — no fork.
"""

from .dicomdir import DicomDirBuilder, check_pydicom_available  # noqa: F401

__all__ = ["DicomDirBuilder", "check_pydicom_available"]
