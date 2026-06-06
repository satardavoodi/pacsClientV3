"""AI-PACS Lite Viewer — portable DICOM viewer bundled on patient CD/DVD media.

This package is intentionally SELF-CONTAINED:

* It must never import anything from ``PacsClient`` or other ``modules.*``
  packages — it is compiled standalone (Nuitka) and shipped on read-only
  media where none of the workstation code exists.
* Only PySide6 (QtCore/QtGui/QtWidgets), pydicom and numpy are allowed as
  dependencies. Optional pylibjpeg codecs are picked up automatically by
  pydicom when bundled.
* No VTK, no MPR, no AI modules, no reporting — basic 2D viewing only
  (open study, series list, scroll, zoom, pan, window/level, toolbar).

Entry points:
* ``python -m modules.cd_burner.portable_viewer`` (dev run)
* ``aipacs_lite_viewer.py`` (Nuitka standalone build entry)
"""

from .viewer_meta import VIEWER_DISPLAY_NAME, VIEWER_EXE_NAME, VIEWER_VERSION

__all__ = ["VIEWER_VERSION", "VIEWER_DISPLAY_NAME", "VIEWER_EXE_NAME"]
