"""Guard: a CLEAN client install must get the fixed CD workflow with zero setup.

Install → Burn CD → Open Portable Viewer → Import DICOM → Display.

Pins:
  * no saved preference            -> the recommended AI-PACS portable viewer
  * the viewer is INCLUDED by default at the Write/Burn step
  * a missing/stale custom-viewer setting must NEVER disable the fixes
    (it used to burn a disc with NO viewer at all)
  * an explicit, still-valid user choice is preserved
  * the shipped config template selects the recommended viewer
  * drag-and-drop / DICOMDIR / extension-less / read-only support are
    UNCONDITIONAL (no flag, nothing to enable)
  * the viewer writes a diagnostic log to a WRITABLE location, never the media
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---------------------------------------------------------------------------
# 1. The shipped config template = the recommended defaults
# ---------------------------------------------------------------------------

def test_shipped_config_template_selects_the_recommended_viewer():
    """`config/lightviewer_settings.json` is seeded on a fresh install."""
    template = json.loads(
        (REPO_ROOT / "config" / "lightviewer_settings.json").read_text(encoding="utf-8")
    )
    assert template.get("viewer_mode") == "default", (
        "a fresh install must default to the bundled AI-PACS portable viewer"
    )
    assert not template.get("light_viewer_path"), (
        "the template must not pin a custom viewer path"
    )
    # The template is seeded on EVERY fresh install. It must not carry one
    # center's identity to another center, or that center's patient discs get
    # stamped with the wrong imaging-center name (and so does AIPACS_MEDIA_INFO.json).
    for key in ("center_name", "center_address", "center_phone"):
        assert template.get(key, "") == "", (
            f"{key} must ship EMPTY — each install enters its own center identity"
        )


# ---------------------------------------------------------------------------
# 2. Viewer selection on a fresh install (no config at all)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_lite_viewer(tmp_path, monkeypatch):
    """A built lite-viewer bundle laid out exactly as the installer ships it.

    Resolution goes through the REAL `modules/cd_burner/lightViewer_dist/...`
    lookup (not the env override), so this exercises the production path a
    client machine takes.
    """
    from modules.cd_burner import viewer_locator

    monkeypatch.delenv(viewer_locator.ENV_OVERRIDE, raising=False)
    bundle = tmp_path / "lightViewer_dist" / "AIPacsLiteViewer"
    bundle.mkdir(parents=True)
    exe = bundle / "AIPacsLiteViewer.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048)
    (bundle / "_internal").mkdir()
    monkeypatch.setattr(viewer_locator, "_module_root", lambda: tmp_path)
    return exe


def test_no_saved_preference_resolves_the_recommended_viewer(fake_lite_viewer):
    from modules.cd_burner.viewer_locator import resolve_default_viewer

    info = resolve_default_viewer()
    assert info is not None
    assert Path(info["path"]) == fake_lite_viewer


def test_fresh_install_viewer_mode_is_default(tmp_path, monkeypatch):
    """No lightviewer_settings.json anywhere -> mode 'default', not 'custom'."""
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.settings_ui import lightviewer_settings as lvs

    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)
    assert not (tmp_path / "lightviewer_settings.json").exists()
    assert lvs.LightViewerSettingsWidget.get_viewer_mode() == lvs.VIEWER_MODE_DEFAULT


def test_fresh_install_selects_and_includes_the_recommended_viewer(
    tmp_path, monkeypatch, fake_lite_viewer
):
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.settings_ui import lightviewer_settings as lvs

    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)
    selection = lvs.LightViewerSettingsWidget.get_viewer_selection()

    assert selection["mode"] == lvs.VIEWER_MODE_DEFAULT
    assert selection["kind"] == "lite"
    assert Path(selection["path"]) == fake_lite_viewer
    # A resolvable path is what makes the burn dialog tick "Include viewer".
    assert selection["path"], "the burn dialog only pre-checks the box when a path resolves"


# ---------------------------------------------------------------------------
# 3. A stale / missing custom setting must NEVER disable the fixes
# ---------------------------------------------------------------------------

def test_missing_custom_viewer_falls_back_to_recommended_not_to_no_viewer(
    tmp_path, monkeypatch, fake_lite_viewer
):
    """THE regression: a stale custom path used to burn a disc with NO viewer."""
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.settings_ui import lightviewer_settings as lvs

    (tmp_path / "lightviewer_settings.json").write_text(json.dumps({
        "viewer_mode": "custom",
        "light_viewer_path": str(tmp_path / "gone" / "OldViewer.exe"),  # does not exist
    }), encoding="utf-8")
    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)

    selection = lvs.LightViewerSettingsWidget.get_viewer_selection()

    assert selection["path"], "a missing custom viewer must not leave the disc viewer-less"
    assert Path(selection["path"]) == fake_lite_viewer
    assert selection["kind"] == "lite"
    assert selection.get("fell_back_from_custom") is True


def test_legacy_config_without_viewer_mode_but_stale_path_still_gets_a_viewer(
    tmp_path, monkeypatch, fake_lite_viewer
):
    """Pre-`viewer_mode` config whose old bundled viewer no longer ships."""
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.settings_ui import lightviewer_settings as lvs

    (tmp_path / "lightviewer_settings.json").write_text(json.dumps({
        "light_viewer_path": str(tmp_path / "lightViewer" / "AiPacs.exe"),  # gone
        "disc_label": "DICOM_IMAGES",
    }), encoding="utf-8")
    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)

    selection = lvs.LightViewerSettingsWidget.get_viewer_selection()
    assert Path(selection["path"]) == fake_lite_viewer


def test_an_explicit_valid_custom_choice_is_preserved(tmp_path, monkeypatch, fake_lite_viewer):
    pytest.importorskip("PySide6")
    from PacsClient.pacs.workstation_ui.settings_ui import lightviewer_settings as lvs

    custom = tmp_path / "MyViewer.exe"
    custom.write_bytes(b"MZ")
    (tmp_path / "lightviewer_settings.json").write_text(json.dumps({
        "viewer_mode": "custom",
        "light_viewer_path": str(custom),
    }), encoding="utf-8")
    monkeypatch.setattr(lvs, "roaming_config_root", lambda: tmp_path)

    selection = lvs.LightViewerSettingsWidget.get_viewer_selection()
    assert selection["mode"] == lvs.VIEWER_MODE_CUSTOM
    assert Path(selection["path"]) == custom
    assert not selection.get("fell_back_from_custom")


# ---------------------------------------------------------------------------
# 4. The viewer-side fixes are UNCONDITIONAL — there is nothing to enable
# ---------------------------------------------------------------------------

def test_import_fixes_are_not_behind_any_flag():
    src = (REPO_ROOT / "modules" / "cd_burner" / "portable_viewer" / "viewer_app.py").read_text(
        encoding="utf-8", errors="replace"
    )
    scan = (REPO_ROOT / "modules" / "cd_burner" / "portable_viewer" / "media_scan.py").read_text(
        encoding="utf-8", errors="replace"
    )
    # External drops accepted, window is a drop target, import wired.
    assert "hasUrls" in src
    assert "self.setAcceptDrops(True)" in src
    assert "on_paths_dropped" in src
    assert "scan_paths" in src and "def scan_paths" in scan
    # No environment gate anywhere in the drop/import path.
    for needle in ("AIPACS_LITE_DROP", "AIPACS_DRAG_DROP", "getenv"):
        assert needle not in scan, f"discovery must not be gated by {needle}"


def test_dicomdir_and_extensionless_support_are_unconditional():
    scan = (REPO_ROOT / "modules" / "cd_burner" / "portable_viewer" / "media_scan.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "DICOMDIR" in scan
    # Suffix-less files must stay in the candidate set (patient CDs use IM000000).
    assert 'suffix == ""' in scan


# ---------------------------------------------------------------------------
# 5. Diagnostic logging goes somewhere writable — never the media
# ---------------------------------------------------------------------------

def test_viewer_logs_to_a_writable_location_and_never_the_media(tmp_path, monkeypatch):
    from modules.cd_burner.portable_viewer import viewer_log

    monkeypatch.setenv(viewer_log.ENV_LOG_DIR, str(tmp_path / "logs"))
    viewer_log._configured_path = None  # fresh
    path = viewer_log.configure_logging()

    assert path is not None
    assert Path(path).parent == tmp_path / "logs"
    assert Path(path).exists()

    import logging

    logging.getLogger("aipacs.lite").info("[LITE-START] hello")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "[LITE-START] hello" in Path(path).read_text(encoding="utf-8")


def test_log_dir_candidates_never_include_the_media_root():
    from modules.cd_burner.portable_viewer import viewer_log

    # The CD is read-only; no candidate may be derived from the media path.
    for candidate in viewer_log.candidate_log_dirs():
        assert "AIPacsLiteViewer" in str(candidate) or "aipacsliteviewer" in str(candidate).lower()


def test_configure_logging_never_raises_when_nothing_is_writable(monkeypatch):
    from modules.cd_burner.portable_viewer import viewer_log

    monkeypatch.setattr(viewer_log, "candidate_log_dirs", lambda: [Path("Z:/nope/nope")])
    viewer_log._configured_path = None
    assert viewer_log.configure_logging() is None  # degrades, does not crash


def test_viewer_main_configures_file_logging_and_logs_the_banner():
    src = (REPO_ROOT / "modules" / "cd_burner" / "portable_viewer" / "viewer_app.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "log_path = configure_logging()" in src
    assert "log_session_banner(" in src
    assert "[LITE-SCAN]" in src
    assert "[LITE-DECODE]" in src
    assert "[LITE-DROP]" in src
