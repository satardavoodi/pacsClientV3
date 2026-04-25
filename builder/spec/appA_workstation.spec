# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


if "__file__" in globals():
    THIS_DIR = Path(__file__).resolve().parent
else:
    THIS_DIR = (Path.cwd() / "builder" / "spec").resolve()
PROJECT_ROOT = THIS_DIR.parent.parent
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from spec_utils import (  # noqa: E402
    app_a_datas,
    graphics_runtime_binaries,
    icon_path_app_a,
    load_hiddenimports,
)


block_cipher = None

datas = list(app_a_datas())
binaries = []
hiddenimports = load_hiddenimports(
    extra=[
        "_project_root",
        "aipacs_runtime",
        "database",
        "database.core",
        "database.manager",
        "PacsClient.utils.data_paths",
        "PacsClient.utils.theme_manager",
        "modules.zeta_boost",
        "pydicom.encoders",
        "pydicom.pixel_data_handlers",
        "pydicom.pixel_data_handlers.numpy_handler",
        "pydicom.fileset",
        "pydicom.uid",
        "pydicom.dataset",
        "pydicom.charset",
        "grpc._cython.cygrpc",
        "qtawesome.iconic_font",
        "qtawesome.fonts",
    ]
)


def _keep_runtime_module_hiddenimport(name: str) -> bool:
    deny_fragments = (
        ".tests",
        ".tests.",
        ".conftest",
        ".example_usage",
        ".test_",
        ".seed_",
    )
    deny_suffixes = (
        ".build",
        ".build_nuitka",
    )
    if any(fragment in name for fragment in deny_fragments):
        return False
    if name.endswith(deny_suffixes):
        return False
    optional_prefixes = (
        "modules.printing",
        "modules.cd_burner",
        "modules.web_browser",
        "modules.EchoMind",
        "modules.mpr.advanced_3d_slicer",
    )
    if any(name == prefix or name.startswith(prefix + ".") for prefix in optional_prefixes):
        return False
    return True


def _safe_extend(target: list, values: list) -> None:
    seen = set(target)
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        target.append(value)


for package_name in ["modules", "database", "PacsClient"]:
    try:
        package_filter = _keep_runtime_module_hiddenimport if package_name in ("modules", "PacsClient") else (lambda name: True)
        _safe_extend(hiddenimports, collect_submodules(package_name, filter=package_filter))
    except Exception:
        pass


for package_name in ["pydicom.encoders", "pydicom.pixel_data_handlers"]:
    try:
        _safe_extend(hiddenimports, collect_submodules(package_name))
    except Exception:
        pass


for package_name in ["vtkmodules", "SimpleITK"]:
    try:
        binaries.extend(collect_dynamic_libs(package_name))
    except Exception:
        pass

_safe_extend(binaries, graphics_runtime_binaries())


for package_name in ["qtawesome"]:
    try:
        datas.extend(collect_data_files(package_name))
    except Exception:
        pass


datas = list(dict.fromkeys(datas))
hiddenimports = sorted(dict.fromkeys(hiddenimports))

excludes = [
    "PyQt5",
    "PyQt6",
    "tkinter",
    "pytest",
    "unittest",
    "jupyter",
    # Dev/test files that must not be bundled into production exe
    "PacsClient.pacs.patient_tab.utils.test",
]


a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[
        str(PROJECT_ROOT / "builder" / "hooks"),
        str(PROJECT_ROOT / "hooks"),
    ],
    runtime_hooks=[
        str(PROJECT_ROOT / "hooks" / "runtime_hook_numpy.py"),
        str(PROJECT_ROOT / "hooks" / "runtime_hook_vtk.py"),
    ],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AIPacs",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_path_app_a(),
    contents_directory="engine",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="AIPacs",
)
