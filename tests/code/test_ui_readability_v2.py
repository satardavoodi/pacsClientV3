"""Guards for the 2026-06-05 UI readability fixes.

1. MPR projection dropdown: high-contrast radio/checkbox indicators (the Qt
   default indicator was dark-on-dark — selected Mode/View unreadable).
2. Voice recorder popup: V2 panel + semantic labelled buttons.
3. EchoMind chat: the seven CLR_* tokens re-point at the live theme when the
   echomind module is on V2 (build default); legacy palette preserved for V1.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PacsClient.utils.v2_style import (  # noqa: E402
    option_control_qss,
    voice_button_qss,
)

_THEME = {
    "accent": "#3182ce",
    "accent_soft": "#21314a",
    "border": "#2d3748",
    "panel_alt_bg": "#1a202c",
    "text_primary": "#f8fafc",
    "text_secondary": "#dbe7f3",
    "text_muted": "#93a4b7",
    "success": "#10b981",
    "danger": "#ef4444",
    "warning": "#f59e0b",
}


# ── option controls (MPR dropdown radios/checkboxes) ──────────────────────
def test_option_controls_have_explicit_indicators():
    qss = option_control_qss(_THEME)
    assert "::indicator" in qss
    # checked = solid accent fill + accent border (the readability fix)
    checked = qss[qss.index("indicator:checked"):]
    assert "#3182ce" in checked
    # rest indicator has a visible border on the panel surface
    assert "2px solid #2d3748" in qss
    # checked label brightens + bolds
    assert "font-weight: 700" in qss


def test_option_controls_defaults_are_safe():
    qss = option_control_qss({})
    assert "::indicator" in qss and "{}" not in qss.replace("{\n", "")


# ── voice buttons ─────────────────────────────────────────────────────────
def test_voice_button_roles_use_semantic_tokens():
    assert "#ef4444" in voice_button_qss(_THEME, "danger")
    assert "#f59e0b" in voice_button_qss(_THEME, "warning")
    assert "#10b981" in voice_button_qss(_THEME, "success")
    assert "#3182ce" in voice_button_qss(_THEME, "neutral")


def test_voice_button_defaults_are_safe():
    qss = voice_button_qss({}, "danger")
    assert "QPushButton" in qss and "hover" in qss and "disabled" in qss


# ── source contracts: applied at the source style sites ───────────────────
def test_mpr_dropdown_applies_v2_after_legacy_styles():
    src = (
        _REPO_ROOT
        / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py"
    ).read_text(encoding="utf-8")
    i_fn = src.index("def _show_mpr_dropdown")
    block = src[i_fn:i_fn + 14000]
    i_panel = block.index("apply_dropdown_panel_v2(dropdown)")
    i_header = block.index("apply_dropdown_header_v2(header)")
    i_opts = block.index("apply_option_controls_v2(")
    # panel after the legacy gradient, header after the purple bar, options
    # after both pickers exist
    assert block.index("stop:0 #1f2937") < i_panel
    assert block.index("stop:0 #7c3aed") < i_header
    assert block.index('QCheckBox("Coronal")') < i_opts


def test_voice_widget_applies_v2_at_source():
    src = (
        _REPO_ROOT
        / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py"
    ).read_text(encoding="utf-8")
    assert "apply_dropdown_panel_v2(self)" in src
    assert src.count("apply_voice_button_v2(") == 6
    # each apply call sits AFTER its legacy setStyleSheet (override order)
    for btn in ("btn_play", "btn_record_pause", "btn_save",
                "btn_delete", "btn_report", "btn_sync"):
        i_legacy = src.index(f"self.{btn}.setStyleSheet(self._btn_style(")
        i_v2 = src.index(f"apply_voice_button_v2(self.{btn}")
        assert i_legacy < i_v2, btn


# ── EchoMind token re-point ───────────────────────────────────────────────
def test_echomind_tokens_gated_and_fail_safe():
    src = (_REPO_ROOT / "modules/EchoMind/ai_chat_config.py").read_text(encoding="utf-8")
    # legacy palette still defined first (V1 byte-identical path)
    i_legacy = src.index('CLR_ACCENT = "#8a8a8a"')
    i_gate = src.index('_get_ui_variant("echomind") == "v2"')
    assert i_legacy < i_gate
    # gated block re-points all seven tokens and never raises
    tail = src[i_gate:]
    for tok in ("CLR_BG", "CLR_BG_PANEL", "CLR_TEXT", "CLR_BORDER",
                "CLR_ACCENT", "CLR_BUBBLE_USER", "CLR_BUBBLE_BOT"):
        assert tok + " = _t.get(" in tail, tok
    assert "except Exception:" in tail and "pass" in tail


def test_echomind_config_importable_with_valid_tokens():
    import importlib

    mod = importlib.import_module("modules.EchoMind.ai_chat_config")
    for tok in ("CLR_BG", "CLR_BG_PANEL", "CLR_TEXT", "CLR_BORDER",
                "CLR_ACCENT", "CLR_BUBBLE_USER", "CLR_BUBBLE_BOT"):
        val = getattr(mod, tok)
        assert isinstance(val, str) and val.startswith("#") and len(val) in (4, 7), (tok, val)


# ── attachments (Audio Recordings / Captured Images) dropdown redesign ─────
_ATTACH_SRC = (
    _REPO_ROOT
    / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py"
).read_text(encoding="utf-8")


def test_attachments_v2_helpers_kill_label_frame_cascade():
    # the card QSS must reset QLabel border (the stray frames around #N/date)
    import re as _re
    m = _re.search(r"def _v2_card_css.*?return \((.*?)\)\n", _ATTACH_SRC, _re.S)
    assert m and "QLabel { background: transparent; border: none; }" in m.group(1)


def test_attachments_v2_applied_after_each_legacy_style():
    src = _ATTACH_SRC
    # popup wrapper, headers, cards, ghosts — all gated overrides present
    assert "apply_dropdown_panel_v2(self)" in src
    assert src.count("apply_dropdown_header_v2(header)") == 2
    assert src.count("self.setStyleSheet(_v2_card_css(_t))") == 2
    # audio actions: exactly one danger (delete); stop demoted to warning
    audio = src[src.index("class _AudioItem"):src.index("class AttachmentsDropdownWidget")]
    assert '_v2_ghost_icon_css(_t, "success")' in audio   # play
    assert '_v2_ghost_icon_css(_t, "warning")' in audio   # stop
    assert '_v2_ghost_icon_css(_t, "accent")' in audio    # report
    assert audio.count('_v2_ghost_icon_css(_t, "danger")') == 1  # delete only
    # audio slider keeps the green (success) identity via tokens
    assert '_v2_slider_css(_t, "success")' in audio


def test_attachments_popup_sizes_to_content():
    assert "def preferred_height" in _ATTACH_SRC
    tm_src = (
        _REPO_ROOT
        / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py"
    ).read_text(encoding="utf-8")
    # both openers (audio + image) replace the fixed 500px well under V2
    assert tm_src.count("dropdown.setFixedHeight(dropdown.preferred_height())") == 2


def test_attachments_preferred_height_clamps():
    # pure logic check without Qt: replicate the formula bounds
    import re as _re
    m = _re.search(r"min\(max_h, max\(min_h, 64 \+ self\.item_row_height \* n\)\)", _ATTACH_SRC)
    assert m is not None
