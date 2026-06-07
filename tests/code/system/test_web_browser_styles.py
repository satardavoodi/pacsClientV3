"""Guards: web-browser unified styling + URL-bar behavior (2026-06-07).

Background: the Add/Edit Favorite dialog was dead in production — six QSS
f-strings used single braces (``QLineEdit {`` instead of ``{{``), which
Python 3.12+ parses as a replacement field whose expression is the bare name
``padding`` → NameError the moment the dialog opened. The styling was also
duplicated (4 identical broken blocks) and mixed three palettes (theme
tokens, a hard-coded navy set, and a hard-coded light set).

These tests are QtWebEngine-free:
- ``modules/web_browser/styles.py`` is imported via file path (importing the
  package would pull QtWebEngineWidgets, which the headless env can't load).
- ``widget.py`` is checked via AST + source pins.
"""
import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_WIDGET_PATH = _ROOT / "modules" / "web_browser" / "widget.py"
_STYLES_PATH = _ROOT / "modules" / "web_browser" / "styles.py"
_MIRROR_DIR = (_ROOT / "builder" / "plugin package" / "packages" / "web_browser"
               / "payload" / "python" / "modules" / "web_browser")

_FAKE_THEME = {
    "accent": "#3b82f6", "accent_hover": "#60a5fa", "accent_pressed": "#1d4ed8",
    "accent_soft": "#1e3a5f", "panel_bg": "#111927", "panel_alt_bg": "#1d2533",
    "panel_deep_bg": "#0d1420", "card_bg": "#141d2c", "border": "#33405a",
    "text_primary": "#f8fafc", "text_secondary": "#dbe7f3", "text_muted": "#93a4b7",
    "menu_hover_bg": "#2a3a52", "menu_active_bg": "#31486a", "button_text": "#ffffff",
    "success": "#10b981", "success_hover": "#34d399", "warning": "#f59e0b",
    "warning_hover": "#fbbf24", "danger": "#ef4444", "danger_hover": "#f87171",
    "info": "#06b6d4", "window_alt_bg": "#1a2330",
}


def _load_styles_module():
    spec = importlib.util.spec_from_file_location("_wb_styles_test", _STYLES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_qss(module):
    return {
        "tool_button": module.tool_button_qss(_FAKE_THEME),
        "icon_button": module.icon_button_qss(_FAKE_THEME),
        "input": module.input_qss(_FAKE_THEME),
        "dialog_primary": module.dialog_button_qss(_FAKE_THEME, primary=True),
        "dialog_secondary": module.dialog_button_qss(_FAKE_THEME, primary=False),
        "state_warning": module.state_button_qss(_FAKE_THEME, "warning"),
        "state_danger": module.state_button_qss(_FAKE_THEME, "danger"),
        "state_success": module.state_button_qss(_FAKE_THEME, "success"),
        "progress_accent": module.progress_qss(_FAKE_THEME, "accent"),
        "progress_danger": module.progress_qss(_FAKE_THEME, "danger"),
        "popup_panel": module.popup_panel_qss(_FAKE_THEME, "TestPanel"),
        "card": module.card_qss(_FAKE_THEME),
        "shell": module.shell_qss(_FAKE_THEME),
        "section_button": module.section_button_qss(_FAKE_THEME),
    }


def test_style_builders_produce_valid_qss():
    """Every builder yields balanced, fully-substituted QSS."""
    module = _load_styles_module()
    for name, qss in _all_qss(module).items():
        assert qss.count("{") == qss.count("}"), f"{name}: unbalanced braces"
        assert "{t[" not in qss and "{_tok" not in qss, f"{name}: unsubstituted placeholder"
        assert "#" in qss, f"{name}: no color resolved"


def test_interactive_styles_cover_hover_and_disabled():
    """Buttons/inputs must define hover; push buttons also disabled state."""
    module = _load_styles_module()
    qss = _all_qss(module)
    for name in ("tool_button", "dialog_primary", "dialog_secondary",
                 "state_warning", "state_danger", "state_success", "icon_button"):
        assert ":hover" in qss[name], f"{name}: missing hover state"
    for name in ("tool_button", "dialog_primary", "dialog_secondary",
                 "state_warning", "state_danger", "state_success", "input"):
        assert ":disabled" in qss[name], f"{name}: missing disabled state"


def test_radius_scale_is_consistent():
    """One radius scale: panels 12 / groups 10 / controls 8."""
    module = _load_styles_module()
    assert module.RADIUS_PANEL == 12
    assert module.RADIUS_GROUP == 10
    assert module.RADIUS_CONTROL == 8
    qss = _all_qss(module)
    assert f"border-radius: {module.RADIUS_CONTROL}px" in qss["tool_button"]
    assert f"border-radius: {module.RADIUS_CONTROL}px" in qss["input"]
    assert f"border-radius: {module.RADIUS_PANEL}px" in qss["popup_panel"]
    assert f"border-radius: {module.RADIUS_GROUP}px" in qss["card"]


def test_no_broken_fstring_qss_in_widget_source():
    """Regression guard for the NameError that killed the favorites dialog.

    A single-brace ``QLineEdit {`` inside an f-string becomes a replacement
    field whose expression is a CSS property name and whose format spec is
    the CSS value — detectable in the AST as a format_spec containing CSS
    text, or a bare-Name expression named like a CSS property.
    """
    tree = ast.parse(_WIDGET_PATH.read_text(encoding="utf-8"))
    css_names = {"padding", "border", "background", "color", "margin", "font"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FormattedValue):
            continue
        assert not (
            isinstance(node.value, ast.Name) and node.value.id in css_names
        ), f"line {node.lineno}: f-string evaluates CSS property '{node.value.id}' — unescaped brace"
        if node.format_spec is not None:
            for part in ast.walk(node.format_spec):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    assert "solid" not in part.value and "px;" not in part.value, (
                        f"line {node.lineno}: CSS leaked into f-string format spec — unescaped brace"
                    )


def test_widget_has_no_hardcoded_hex_colors():
    """All widget.py colors must come from theme tokens (fallback hex lives
    only in styles.py builders)."""
    import re
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    hits = [
        f"line {src[:m.start()].count(chr(10)) + 1}: {m.group(0)}"
        for m in re.finditer(r"#[0-9a-fA-F]{6}\b", src)
    ]
    assert not hits, f"hard-coded hex colors in widget.py: {hits}"


def test_url_bar_behavior_pins():
    """URL bar: user edits must never be clobbered; reload doubles as stop."""
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    assert "_url_user_editing" in src, "user-edit tracking flag missing"
    assert "textEdited.connect" in src, "textEdited (user-only signal) must drive the edit flag"
    assert "_sync_url_bar" in src, "central URL-bar sync helper missing"
    assert "self.web_view.stop()" in src, "stop-while-loading must be available via the reload button"
    # exactly two HOME_URL loads: setup_profile (initial) + navigate_home —
    # the third (setup_ui) was a throwaway load on the default profile.
    assert src.count("setUrl(QUrl(HOME_URL))") == 2, (
        "HOME_URL must be loaded only from setup_profile and navigate_home"
    )


def test_widget_uses_shared_style_builders():
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    for helper in ("tool_button_qss", "input_qss", "dialog_button_qss",
                   "state_button_qss", "progress_qss", "popup_panel_qss"):
        assert helper in src, f"widget.py must use shared builder {helper}"


def test_plugin_mirror_parity():
    """Plugin payload mirror must carry the same fixes."""
    if not _MIRROR_DIR.exists():
        pytest.skip("plugin payload mirror not present")
    mirror_widget = _MIRROR_DIR / "widget.py"
    mirror_styles = _MIRROR_DIR / "styles.py"
    assert mirror_styles.exists(), "styles.py missing from plugin payload mirror"
    assert mirror_widget.read_text(encoding="utf-8", errors="ignore") == _WIDGET_PATH.read_text(
        encoding="utf-8", errors="ignore"
    ), "plugin payload widget.py mirror is stale"
    assert mirror_styles.read_text(encoding="utf-8", errors="ignore") == _STYLES_PATH.read_text(
        encoding="utf-8", errors="ignore"
    ), "plugin payload styles.py mirror is stale"
