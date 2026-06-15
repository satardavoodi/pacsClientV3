"""Default-viewer resolution: lite build → legacy fallback → env override."""

from pathlib import Path

import pytest

from modules.cd_burner import viewer_locator
from modules.cd_burner.viewer_locator import (
    default_viewer_hint,
    resolve_default_viewer,
)


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(viewer_locator, "_module_root", lambda: tmp_path)
    monkeypatch.delenv(viewer_locator.ENV_OVERRIDE, raising=False)
    return tmp_path


def _make_lite(root: Path) -> Path:
    exe = root / "lightViewer_dist" / "AIPacsLiteViewer" / "AIPacsLiteViewer.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ lite")
    return exe


def _make_legacy(root: Path, name: str = "AiPacs.exe") -> Path:
    exe = root / "lightViewer" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ legacy")
    return exe


def test_no_viewer_resolves_none_with_build_hint(fake_root):
    assert resolve_default_viewer() is None
    assert "build_lite_viewer" in default_viewer_hint()


def test_lite_build_preferred_over_legacy(fake_root):
    lite = _make_lite(fake_root)
    _make_legacy(fake_root)

    info = resolve_default_viewer()
    assert info is not None
    assert info["kind"] == "lite"
    assert Path(info["path"]) == lite
    assert info["display_name"] == "AI-PACS Lite Viewer"


def test_legacy_fallback_prefers_aipacs_exe(fake_root):
    _make_legacy(fake_root, "Other.exe")
    preferred = _make_legacy(fake_root, "AiPacs.exe")

    info = resolve_default_viewer()
    assert info is not None
    assert info["kind"] == "legacy"
    assert Path(info["path"]) == preferred
    assert "legacy" in default_viewer_hint().lower()


def test_env_override_file_and_dir(fake_root, monkeypatch, tmp_path):
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    exe = override_dir / "MyViewer.exe"
    exe.write_bytes(b"MZ override")

    monkeypatch.setenv(viewer_locator.ENV_OVERRIDE, str(exe))
    info = resolve_default_viewer()
    assert info["kind"] == "override"
    assert Path(info["path"]) == exe

    monkeypatch.setenv(viewer_locator.ENV_OVERRIDE, str(override_dir))
    info = resolve_default_viewer()
    assert Path(info["path"]) == exe


def test_env_override_invalid_falls_through(fake_root, monkeypatch):
    monkeypatch.setenv(viewer_locator.ENV_OVERRIDE, str(fake_root / "missing.exe"))
    lite = _make_lite(fake_root)
    info = resolve_default_viewer()
    assert info["kind"] == "lite"
    assert Path(info["path"]) == lite


def test_frozen_candidate_roots_find_viewer(tmp_path, monkeypatch):
    """When frozen, the viewer next to the exe / in _internal is found even
    if the module's own dir has no bundle (the installed-client guarantee)."""
    monkeypatch.delenv(viewer_locator.ENV_OVERRIDE, raising=False)
    # Module dir = empty; exe dir carries the bundle under _internal.
    empty_module_dir = tmp_path / "engine_modules" / "cd_burner"
    empty_module_dir.mkdir(parents=True)
    monkeypatch.setattr(viewer_locator, "_module_root", lambda: empty_module_dir)

    exe_dir = tmp_path / "app"
    lite = exe_dir / "_internal" / "modules" / "cd_burner" / "lightViewer_dist" / "AIPacsLiteViewer" / "AIPacsLiteViewer.exe"
    lite.parent.mkdir(parents=True)
    lite.write_bytes(b"MZ lite")

    monkeypatch.setattr(viewer_locator.sys, "frozen", True, raising=False)
    monkeypatch.setattr(viewer_locator.sys, "executable", str(exe_dir / "AIPacs.exe"), raising=False)

    info = resolve_default_viewer()
    assert info is not None
    assert info["kind"] == "lite"
    assert Path(info["path"]) == lite.resolve()


def test_not_frozen_ignores_exe_dir(fake_root, monkeypatch):
    """Non-frozen runs only look next to the module (no exe-dir scanning)."""
    monkeypatch.setattr(viewer_locator.sys, "frozen", False, raising=False)
    # No installed module_packages payload in this isolated env either.
    import aipacs_runtime
    monkeypatch.setattr(aipacs_runtime, "bundled_module_packages_search_roots", lambda: [])
    assert resolve_default_viewer() is None  # fake_root is empty


def test_installed_payload_root_resolves_viewer(fake_root, monkeypatch, tmp_path):
    """When cd_burner is excluded from the engine (PyInstaller build), the
    viewer must still resolve from the installed run_cd plugin payload."""
    monkeypatch.delenv(viewer_locator.ENV_OVERRIDE, raising=False)
    # Module dir empty (engine ships no viewer); payload carries it.
    import aipacs_runtime
    mp_root = tmp_path / "module_packages"
    lite = (mp_root / "run_cd" / "payload" / "python" / "modules" / "cd_burner"
            / "lightViewer_dist" / "AIPacsLiteViewer" / "AIPacsLiteViewer.exe")
    lite.parent.mkdir(parents=True)
    lite.write_bytes(b"MZ lite")
    monkeypatch.setattr(aipacs_runtime, "bundled_module_packages_search_roots", lambda: [mp_root])

    info = resolve_default_viewer()
    assert info is not None
    assert info["kind"] == "lite"
    assert Path(info["path"]) == lite.resolve()
