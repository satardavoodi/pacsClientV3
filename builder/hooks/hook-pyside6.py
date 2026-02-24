"""Custom PyInstaller hook for PySide6 (case-insensitive filename on Windows)."""

from _hook_helpers import pyside6_hook_payload

hiddenimports, datas, binaries = pyside6_hook_payload()

