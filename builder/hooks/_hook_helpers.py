from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


def _keep_runtime_vtk_submodule(name: str) -> bool:
    deny_prefixes = (
        "vtkmodules.generate_pyi",
        "vtkmodules.gtk",
        "vtkmodules.test",
        "vtkmodules.tk",
        "vtkmodules.web",
        "vtkmodules.wx",
    )
    return not name.startswith(deny_prefixes)


def _iter_file_tuples(root: Path, dest_root: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parent = p.parent.relative_to(root)
        dest = Path(dest_root) / rel_parent
        out.append((str(p), str(dest).replace("\\", "/")))
    return out


def _safe_import_module(name: str):
    try:
        import importlib

        return importlib.import_module(name)
    except Exception:
        return None


def pyside6_hook_payload() -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]:
    hiddenimports = []
    datas: list[tuple[str, str]] = []
    binaries: list[tuple[str, str]] = []

    binaries.extend(collect_dynamic_libs("PySide6"))

    pyside6 = _safe_import_module("PySide6")
    if not pyside6 or not getattr(pyside6, "__file__", None):
        return hiddenimports, datas, binaries

    pkg_dir = Path(pyside6.__file__).resolve().parent
    plugins_dir = pkg_dir / "plugins"
    qml_dir = pkg_dir / "qml"
    resources_dir = pkg_dir / "resources"
    translations_dir = pkg_dir / "translations"

    plugin_subdirs = [
        "platforms",
        "imageformats",
        "styles",
        "iconengines",
        "tls",
        "networkinformation",
        "multimedia",
        "position",
        "sqldrivers",
        "webview",
        "webenginecore",
    ]
    for sub in plugin_subdirs:
        datas.extend(_iter_file_tuples(plugins_dir / sub, f"PySide6/plugins/{sub}"))

    # WebEngine resources and ICU files live here for many PySide6 builds.
    datas.extend(_iter_file_tuples(resources_dir, "PySide6/resources"))
    datas.extend(_iter_file_tuples(translations_dir, "PySide6/translations"))
    datas.extend(_iter_file_tuples(qml_dir, "PySide6/qml"))

    hiddenimports.extend(
        [
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
            "PySide6.QtNetwork",
            "PySide6.QtSvg",
            "PySide6.QtPrintSupport",
            "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineWidgets",
        ]
    )
    # Built-in hooks cover a lot, but this keeps the hook self-sufficient.
    return sorted(set(hiddenimports)), _dedupe_tuples(datas), _dedupe_tuples(binaries)


def vtk_hook_payload() -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]:
    hiddenimports = collect_submodules("vtkmodules", filter=_keep_runtime_vtk_submodule)
    for extra in [
        "vtkmodules.util",
        "vtkmodules.util.data_model",
        "vtkmodules.util.execution_model",
        "vtkmodules.util.numpy_support",
        "vtkmodules.qt.QVTKRenderWindowInteractor",
    ]:
        if extra not in hiddenimports:
            hiddenimports.append(extra)
    datas = collect_data_files("vtkmodules")
    binaries = []
    binaries.extend(collect_dynamic_libs("vtkmodules"))
    return sorted(set(hiddenimports)), _dedupe_tuples(datas), _dedupe_tuples(binaries)


def simpleitk_hook_payload() -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]:
    hiddenimports = ["SimpleITK._SimpleITK"]
    datas = collect_data_files("SimpleITK")
    binaries = []
    try:
        binaries.extend(collect_dynamic_libs("SimpleITK"))
    except Exception:
        pass
    return hiddenimports, _dedupe_tuples(datas), _dedupe_tuples(binaries)


def _dedupe_tuples(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen = set()
    for src, dest in items:
        key = (src.lower(), dest.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((src, dest))
    return out

