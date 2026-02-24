"""Custom PyInstaller hook for SimpleITK (case-insensitive filename on Windows)."""

from _hook_helpers import simpleitk_hook_payload

hiddenimports, datas, binaries = simpleitk_hook_payload()

