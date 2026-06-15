"""The run_cd plugin payload must ship the lite viewer (installed-client
guarantee) and must NOT carry the legacy 72 MB viewer / *.rar bloat."""

import shutil

import pytest

from builder import materialize_plugin_packages as mpp


def _make_lite_bundle(root):
    """Minimal but 'complete' lite viewer bundle under modules/cd_burner."""
    bundle = root / "lightViewer_dist" / "AIPacsLiteViewer"
    (bundle / "_internal" / "PySide6" / "plugins" / "platforms").mkdir(parents=True)
    (bundle / "AIPacsLiteViewer.exe").write_bytes(b"MZ")
    (bundle / "_internal" / "base_library.zip").write_bytes(b"PK")
    (bundle / "_internal" / "python313.dll").write_bytes(b"dll")
    (bundle / "_internal" / "PySide6" / "plugins" / "platforms" / "qwindows.dll").write_bytes(b"dll")


def test_validate_passes_with_complete_bundle(tmp_path):
    pkg = tmp_path / "run_cd"
    cd = pkg / "payload" / "python" / "modules" / "cd_burner"
    cd.mkdir(parents=True)
    _make_lite_bundle(cd)
    mpp._validate_run_cd_lite_viewer(pkg)  # must not raise


def test_validate_fails_without_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv(mpp._ALLOW_MISSING_LITE_VIEWER_ENV, raising=False)
    pkg = tmp_path / "run_cd"
    (pkg / "payload" / "python" / "modules" / "cd_burner").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="lite viewer|Lite Viewer"):
        mpp._validate_run_cd_lite_viewer(pkg)


def test_validate_fails_with_incomplete_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv(mpp._ALLOW_MISSING_LITE_VIEWER_ENV, raising=False)
    pkg = tmp_path / "run_cd"
    cd = pkg / "payload" / "python" / "modules" / "cd_burner"
    bundle = cd / "lightViewer_dist" / "AIPacsLiteViewer"
    bundle.mkdir(parents=True)
    (bundle / "AIPacsLiteViewer.exe").write_bytes(b"MZ")  # exe but no _internal
    with pytest.raises(RuntimeError):
        mpp._validate_run_cd_lite_viewer(pkg)


def test_escape_hatch_allows_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(mpp._ALLOW_MISSING_LITE_VIEWER_ENV, "1")
    pkg = tmp_path / "run_cd"
    (pkg / "payload" / "python" / "modules" / "cd_burner").mkdir(parents=True)
    mpp._validate_run_cd_lite_viewer(pkg)  # warns, does not raise


def test_copy_source_tree_excludes_legacy_and_rar(tmp_path, monkeypatch):
    """_copy_source_tree must drop legacy lightViewer/ and *.rar but keep
    lightViewer_dist + .py sources."""
    project = tmp_path / "project"
    src = project / "modules" / "cd_burner"
    src.mkdir(parents=True)
    (src / "cd_burn_manager.py").write_text("x = 1", encoding="utf-8")
    (src / "lightViewer").mkdir()
    (src / "lightViewer" / "AiPacs.exe").write_bytes(b"MZ legacy 72MB")
    (src / "lightViewer.rar").write_bytes(b"RAR")
    _make_lite_bundle(src)

    monkeypatch.setattr(mpp, "PROJECT_ROOT", project)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    mpp._copy_source_tree(pkg, ["modules/cd_burner"])

    dest = pkg / "payload" / "python" / "modules" / "cd_burner"
    assert (dest / "cd_burn_manager.py").is_file()
    assert (dest / "lightViewer_dist" / "AIPacsLiteViewer" / "AIPacsLiteViewer.exe").is_file()
    assert not (dest / "lightViewer").exists()        # legacy excluded
    assert not (dest / "lightViewer.rar").exists()    # archive excluded
