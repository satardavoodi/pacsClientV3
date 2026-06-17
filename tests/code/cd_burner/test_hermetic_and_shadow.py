"""Adopted from the lite-viewer eval report (2026-06-16):
1. hermetic frozen sys.path filter (prevents host numpy/site-packages clashes)
2. namespace-shadow validators ignore non-Python (data) folders.
"""

import os

from modules.cd_burner.portable_viewer._hermetic import compute_hermetic_path


# ---------------------------------------------------------------------------
# Hermetic sys.path
# ---------------------------------------------------------------------------

def test_hermetic_keeps_only_bundle_paths():
    bundle = os.path.abspath(os.path.join("X", "app", "_internal"))
    exe_dir = os.path.abspath(os.path.join("X", "app"))
    path = [
        bundle,
        os.path.join(bundle, "base_library.zip"),
        os.path.join(bundle, "numpy"),
        r"C:\Python313\Lib\site-packages",      # host site-packages — drop
        r"C:\Python313\Lib\site-packages\numpy",  # conflicting numpy — drop
        "",                                       # CWD — drop
        exe_dir,
    ]
    kept = compute_hermetic_path(path, [bundle, exe_dir])
    assert bundle in kept
    assert os.path.join(bundle, "numpy") in kept
    assert exe_dir in kept
    assert r"C:\Python313\Lib\site-packages" not in kept
    assert r"C:\Python313\Lib\site-packages\numpy" not in kept
    assert "" not in kept


def test_hermetic_no_bundle_returns_empty():
    assert compute_hermetic_path([r"C:\foo", ""], [r"D:\bundle"]) == []


def test_hermetic_handles_prefix_not_substring():
    # "_internal2" must NOT be treated as inside "_internal".
    bundle = os.path.abspath("_internal")
    sibling = os.path.abspath("_internal2") + os.sep + "x"
    kept = compute_hermetic_path([bundle, sibling], [bundle])
    assert bundle in kept
    assert sibling not in kept


# ---------------------------------------------------------------------------
# Shadow validators ignore data folders
# ---------------------------------------------------------------------------

def _build_engine_and_payload(tmp_path, *, engine_extra_data: bool):
    """A modules/<mod> with a real subpackage + data folders. Optionally give
    the engine an EXTRA data folder the payload lacks (the false-positive case)."""
    project = tmp_path / "project"
    engine = project / "modules" / "cd_burner"
    (engine / "portable_viewer").mkdir(parents=True)   # real subpackage
    (engine / "portable_viewer" / "__init__.py").write_text("", encoding="utf-8")
    (engine / "assets").mkdir()                         # data folder
    (engine / "assets" / "cd_icon.png").write_bytes(b"PNG")
    (engine / "__init__.py").write_text("", encoding="utf-8")
    if engine_extra_data:
        # Engine has a big data dir the payload deliberately omits.
        (engine / "lightViewer_dist" / "AIPacsLiteViewer").mkdir(parents=True)
        (engine / "lightViewer_dist" / "AIPacsLiteViewer" / "v.exe").write_bytes(b"MZ")

    pkg = tmp_path / "pkg"
    payload_cd = pkg / "payload" / "python" / "modules" / "cd_burner"
    (payload_cd / "portable_viewer").mkdir(parents=True)
    (payload_cd / "portable_viewer" / "__init__.py").write_text("", encoding="utf-8")
    (payload_cd / "assets").mkdir()
    (payload_cd / "assets" / "cd_icon.png").write_bytes(b"PNG")
    (payload_cd / "__init__.py").write_text("", encoding="utf-8")
    return project, pkg


def test_materialize_shadow_ignores_data_dirs(tmp_path, monkeypatch):
    from builder import materialize_plugin_packages as mpp

    project, pkg = _build_engine_and_payload(tmp_path, engine_extra_data=True)
    monkeypatch.setattr(mpp, "PROJECT_ROOT", project)
    # Engine has lightViewer_dist (data) that payload lacks — must NOT raise,
    # because a data folder cannot shadow an import.
    mpp._validate_plugin_no_namespace_shadow(pkg, "cd_burner")


def test_materialize_shadow_still_catches_missing_python_subpkg(tmp_path, monkeypatch):
    from builder import materialize_plugin_packages as mpp
    import pytest

    project, pkg = _build_engine_and_payload(tmp_path, engine_extra_data=False)
    # Give the engine a REAL python subpackage the payload lacks → must raise.
    real = project / "modules" / "cd_burner" / "curved_extra"
    real.mkdir()
    (real / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(mpp, "PROJECT_ROOT", project)
    with pytest.raises(ValueError, match="PARTIAL namespace shadow"):
        mpp._validate_plugin_no_namespace_shadow(pkg, "cd_burner")
