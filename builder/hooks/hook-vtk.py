"""Custom PyInstaller hook for vtk wrapper package."""

from _hook_helpers import vtk_hook_payload

hiddenimports, datas, binaries = vtk_hook_payload()

