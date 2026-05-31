"""Tests for the per-widget V2 styling helpers (Phase 2 scaffold).

Pure-function / flag tests — no Qt required. They prove:
  * home_is_v2() reflects the gate and never raises,
  * the Search-button V2 QSS uses accent tokens and drops the V1 green,
  * empty/partial theme dicts fall back to safe defaults.
"""
from __future__ import annotations

from PacsClient.utils import v2_style


def test_home_is_v2_reflects_flag(monkeypatch):
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v1")
    assert v2_style.home_is_v2() is False
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v2")
    assert v2_style.home_is_v2() is True


def test_home_is_v2_never_raises(monkeypatch):
    def boom(module=None):
        raise RuntimeError("config blew up")

    monkeypatch.setattr(v2_style, "get_ui_variant", boom)
    assert v2_style.home_is_v2() is False


def test_search_button_qss_uses_accent_tokens():
    theme = {
        "accent": "#3182ce",
        "accent_hover": "#4a90d9",
        "accent_pressed": "#2a6cb0",
        "button_text": "#ffffff",
    }
    qss = v2_style.search_button_qss(theme)
    assert "#3182ce" in qss          # accent applied
    assert "#4a90d9" in qss          # hover applied
    assert "#2a6cb0" in qss          # pressed applied
    assert "#059669" not in qss      # the V1 green is gone


def test_search_button_qss_defaults_are_safe():
    qss = v2_style.search_button_qss({})
    assert "#3182ce" in qss          # default accent
    assert "QPushButton" in qss
    assert "QPushButton:hover" in qss


def test_secondary_button_qss_is_outline_and_drops_purple():
    theme = {"border": "#33415a", "text_secondary": "#dbe7f3",
             "panel_alt_bg": "#1b2433", "accent": "#3182ce"}
    qss = v2_style.secondary_button_qss(theme)
    assert "background: transparent;" in qss   # ghost/outline, not a filled fill
    assert "#33415a" in qss                     # token border
    assert "#dbe7f3" in qss                     # token text
    assert "#7c3aed" not in qss                 # the V1 off-palette purple is gone


def test_table_header_qss_uses_tokens():
    theme = {"menu_bg": "#223246", "text_secondary": "#dbe7f3", "border": "#2d3748"}
    qss = v2_style.table_header_qss(theme)
    assert "QHeaderView::section" in qss
    assert "#223246" in qss                     # menu_bg token
    assert "#1a202c" not in qss                  # the V1 hard-coded header bg is gone


def test_new_qss_defaults_are_safe():
    assert "QPushButton" in v2_style.secondary_button_qss({})
    assert "QHeaderView::section" in v2_style.table_header_qss({})


def test_results_table_qss_density_and_soft_selection():
    theme = {
        "panel_bg": "#111927", "panel_alt_bg": "#1a202c", "border": "#2d3748",
        "text_primary": "#f8fafc", "text_secondary": "#dbe7f3", "menu_bg": "#223246",
        "accent_soft": "#21314a", "accent": "#3182ce",
    }
    qss = v2_style.results_table_qss(theme)
    assert "padding: 8px 10px;" in qss      # roomier than V1's 2px
    assert "#21314a" in qss                  # soft accent selection token
    assert "gridline-color: transparent;" in qss
    assert "QHeaderView::section" in qss


def test_results_table_qss_defaults_are_safe():
    qss = v2_style.results_table_qss({})
    assert "QTableWidget" in qss
    assert "QTableWidget::item:selected" in qss


def test_viewer_is_v2_reflects_flag(monkeypatch):
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v1")
    assert v2_style.viewer_is_v2() is False
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v2")
    assert v2_style.viewer_is_v2() is True


def test_thumbnail_header_qss_uses_accent_not_purple():
    qss = v2_style.thumbnail_header_qss({"accent": "#3182ce", "button_text": "#f7fafc"})
    assert "#3182ce" in qss              # real accent
    assert "#7c3aed" not in qss          # the V1 purple fallback is gone
    assert "#5b21b6" not in qss          # ...and its gradient stop
    assert "QLabel" in qss


def test_thumbnail_header_qss_defaults_are_safe():
    qss = v2_style.thumbnail_header_qss({})
    assert "#3182ce" in qss              # default accent (not purple)
    assert "border-radius: 8px;" in qss


def test_home_panel_header_qss_is_flat_not_filled_accent():
    theme = {"text_secondary": "#dbe7f3", "panel_alt_bg": "#1b2433",
             "border": "#33415a", "accent": "#3182ce"}
    qss = v2_style.home_panel_header_qss(theme)
    assert "#1b2433" in qss               # quiet panel surface, not the accent gradient
    assert "qlineargradient" not in qss   # heavy filled gradient is gone
    assert "#3182ce" not in qss           # not a filled accent header anymore
    assert "QLabel" in qss


def test_home_count_chip_qss_is_muted():
    qss = v2_style.home_count_chip_qss({"text_muted": "#93a4b7",
                                        "panel_alt_bg": "#1b2433", "border": "#33415a"})
    assert "#93a4b7" in qss               # muted text
    assert "qlineargradient" not in qss
    assert "border-radius: 8px;" in qss


def test_home_header_chip_defaults_are_safe():
    assert "QLabel" in v2_style.home_panel_header_qss({})
    assert "QLabel" in v2_style.home_count_chip_qss({})


def test_home_toolbar_button_qss_roles():
    theme = {"text_secondary": "#e5e7eb", "accent": "#3182ce", "accent_hover": "#4a90d9",
             "accent_soft": "#21314a", "danger": "#ef4444", "button_text": "#ffffff"}
    primary = v2_style.home_toolbar_button_qss(theme, "primary")
    danger = v2_style.home_toolbar_button_qss(theme, "danger")
    neutral = v2_style.home_toolbar_button_qss(theme, "neutral")
    # primary = the single filled-accent action (not a gradient block)
    assert "background: #3182ce;" in primary
    assert "qlineargradient" not in primary
    # danger + neutral are flat ghost at rest
    assert "background: transparent;" in danger
    assert "background: transparent;" in neutral
    # danger reddens only on hover (soft rgba of danger)
    assert "rgba(239, 68, 68" in danger
    # neutral hovers to soft accent
    assert "#21314a" in neutral
    # none of them is a heavy gradient block
    assert "qlineargradient" not in danger and "qlineargradient" not in neutral


def test_home_toolbar_button_qss_defaults_are_safe():
    assert "QPushButton" in v2_style.home_toolbar_button_qss({})
    assert "QPushButton" in v2_style.home_toolbar_button_qss({}, "primary")


def test_settings_is_v2_reflects_flag(monkeypatch):
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v1")
    assert v2_style.settings_is_v2() is False
    monkeypatch.setattr(v2_style, "get_ui_variant", lambda module=None: "v2")
    assert v2_style.settings_is_v2() is True


def test_settings_stylesheet_qss_uses_tokens_and_calms_groupbox_title():
    theme = {"accent": "#3182ce", "accent_soft": "#21314a", "panel_bg": "#111927",
             "panel_alt_bg": "#1a202c", "card_bg": "#0f1319", "border": "#2d3748",
             "text_secondary": "#dbe7f3", "button_text": "#ffffff"}
    qss = v2_style.settings_stylesheet_qss(theme, arrow_icon="x.png")
    assert "QTabWidget#SettingsTabWidget" in qss        # stays scoped
    assert "#3182ce" in qss                              # accent token applied
    assert "#3b82f6" not in qss                          # the V1 hard-coded blue is gone
    assert "font-size: 13px; font-weight: 700;" in qss   # calmed GroupBox title (was 28px/900)
    assert "font-size: 28px" not in qss                  # the jarring big title is gone
    assert "url(x.png)" in qss                           # arrow placeholder substituted
    assert "__ACCENT__" not in qss and "__BORDER__" not in qss  # all placeholders replaced


def test_settings_stylesheet_qss_defaults_are_safe():
    qss = v2_style.settings_stylesheet_qss({})
    assert "QTabWidget#SettingsTabWidget" in qss
    assert "__" not in qss.replace("__ARROW__", "")  # no leftover token placeholders (arrow may be empty)


def test_tool_button_qss_is_ghost_with_accent_active():
    theme = {"text_secondary": "#e5e7eb", "panel_alt_bg": "#1a202c",
             "accent": "#3182ce", "button_text": "#ffffff", "border": "#2d3748"}
    qss = v2_style.tool_button_qss(theme, 24, 24)
    assert "background: transparent;" in qss        # ghost, not a filled block
    assert "qproperty-iconSize: 24px 24px;" in qss  # icon size preserved
    assert "QPushButton:checked" in qss and "#3182ce" in qss  # active = accent
    assert "QPushButton:hover" in qss


def test_tool_button_qss_defaults_are_safe():
    qss = v2_style.tool_button_qss({})
    assert "QPushButton" in qss
    assert "background: transparent;" in qss


def test_qtoolbutton_qss_is_ghost_with_qtoolbutton_selectors():
    theme = {"text_secondary": "#e5e7eb", "panel_alt_bg": "#1a202c",
             "accent": "#3182ce", "button_text": "#ffffff", "border": "#2d3748"}
    qss = v2_style.qtoolbutton_qss(theme)
    assert "QToolButton {" in qss                  # correct selector for QToolButton
    assert "QPushButton" not in qss                 # must NOT use QPushButton selector
    assert "background: transparent;" in qss        # ghost
    assert "QToolButton:checked" in qss and "#3182ce" in qss  # active = accent


def test_qtoolbutton_qss_defaults_are_safe():
    qss = v2_style.qtoolbutton_qss({})
    assert "QToolButton" in qss
    assert "background: transparent;" in qss


def test_pushbutton_ghost_qss_radius_and_ghost():
    theme = {"text_secondary": "#e5e7eb", "panel_alt_bg": "#1a202c",
             "accent": "#3182ce", "button_text": "#ffffff", "border": "#2d3748"}
    # default radius
    qss = v2_style.pushbutton_ghost_qss(theme)
    assert "background: transparent;" in qss
    assert "border-radius: 8px;" in qss
    assert "QPushButton:checked" in qss and "#3182ce" in qss
    # split-left geometry preserved
    left = v2_style.pushbutton_ghost_qss(theme, "8px 0px 0px 8px")
    assert "border-radius: 8px 0px 0px 8px;" in left
    # split-right geometry preserved
    right = v2_style.pushbutton_ghost_qss(theme, "0px 8px 8px 0px")
    assert "border-radius: 0px 8px 8px 0px;" in right


def test_pushbutton_ghost_qss_defaults_are_safe():
    qss = v2_style.pushbutton_ghost_qss({})
    assert "QPushButton" in qss
    assert "background: transparent;" in qss


def test_split_container_hover_qss_unifies_both_halves():
    theme = {"accent": "#3182ce", "accent_soft": "#21314a", "button_text": "#ffffff"}
    qss = v2_style.split_container_hover_qss(theme)
    # container :hover targets BOTH halves so they highlight together
    assert 'QWidget:hover QPushButton[_theme_style_type="split_left"]' in qss
    assert 'QWidget:hover QPushButton[_theme_style_type="split_right"]' in qss
    # seamless join: left drops right border, right drops left border
    assert "border-right: none;" in qss
    assert "border-left: none;" in qss
    # soft accent fill + accent border
    assert "#21314a" in qss and "#3182ce" in qss
    # active (checked) half keeps the solid accent fill
    assert ":checked" in qss


def test_split_container_hover_qss_defaults_are_safe():
    qss = v2_style.split_container_hover_qss({})
    assert "QWidget:hover QPushButton" in qss
    assert "#3182ce" in qss


def test_badge_qss_uses_badge_blue_not_red():
    qss = v2_style.badge_qss({"badge_blue": "#1e40af", "accent": "#3182ce"})
    assert "#1e40af" in qss          # calm badge blue
    assert "#dc2626" not in qss      # not the alarming danger red
    assert "QLabel" in qss


def test_badge_qss_defaults_are_safe():
    qss = v2_style.badge_qss({})
    assert "#3182ce" in qss          # falls back to accent (still not red)
    assert "border-radius: 7px;" in qss


def test_split_box_qss_is_one_container_box_with_states():
    theme = {"accent": "#3182ce", "accent_soft": "#21314a"}
    qss = v2_style.split_box_qss(theme)
    assert 'QWidget[v2box="true"]' in qss            # scoped to the container only
    assert "border-radius: 8px;" in qss               # the single box
    assert '[groupHover="true"]' in qss and "#21314a" in qss   # unified hover
    assert '[active="true"]' in qss and "#3182ce" in qss       # one selection state


def test_split_inner_qss_is_transparent_no_box():
    qss = v2_style.split_inner_qss({"text_secondary": "#e5e7eb"})
    assert "background: transparent;" in qss
    assert "border: none;" in qss                     # no inner box
    assert "border-radius: 0px;" in qss


def test_split_box_and_inner_defaults_are_safe():
    assert 'QWidget[v2box="true"]' in v2_style.split_box_qss({})
    assert "QPushButton" in v2_style.split_inner_qss({})


def test_split_inner_side_qss_draws_unified_box():
    left = v2_style.split_inner_side_qss({}, "left")
    right = v2_style.split_inner_side_qss({}, "right")
    # rest is transparent, but each half now draws its OWN box on hover/selection
    assert "background: transparent;" in left          # rest state
    assert "#3182ce" in left                            # default accent box (hover/checked)
    assert 'QPushButton[groupHover="true"]' in left     # unified-hover hook
    assert "QPushButton:checked" in left                # selected = accent fill
    # split geometry joins the two halves into one rounded box
    assert "border-right: none;" in left                # left drops its right border
    assert "border-left: none;" in right                # right drops its left border
    assert "border-top-left-radius: 8px;" in left       # left-rounded corners
    assert "border-top-right-radius: 8px;" in right      # right-rounded corners
    # slim dropdown strip vs main tool width
    assert "max-width: 22px;" in left
    assert "min-width: 40px;" in right
    assert "max-width" not in right


def test_dropdown_item_qss_two_column_alignment():
    theme = {"text_secondary": "#e5e7eb", "accent": "#3182ce",
             "accent_soft": "#21314a", "button_text": "#ffffff"}
    qss = v2_style.dropdown_item_qss(theme)
    assert "qproperty-iconSize: 18px 18px;" in qss   # one uniform icon column
    assert "text-align: left;" in qss                 # labels left-align, not centered
    assert "padding: 7px 14px 7px 12px;" in qss       # consistent left padding (icon column)
    assert "#21314a" in qss                            # soft accent hover
    assert "QPushButton:checked" in qss and "#3182ce" in qss  # selected = accent fill


def test_dropdown_item_qss_defaults_are_safe():
    qss = v2_style.dropdown_item_qss({})
    assert "QPushButton" in qss
    assert "text-align: left;" in qss
    assert "qproperty-iconSize: 18px 18px;" in qss


def test_dropdown_status_row_qss_quiets_legacy_colors():
    theme = {"accent": "#3182ce", "accent_soft": "#21314a"}
    rest = v2_style.dropdown_status_row_qss(theme, is_current=False)
    cur = v2_style.dropdown_status_row_qss(theme, is_current=True)
    # non-current row = transparent rest, soft accent hover, no green/amber/purple
    assert "background: transparent;" in rest
    assert "#21314a" in rest                      # accent_soft hover
    assert "#059669" not in rest and "#f59e0b" not in rest and "#8b5cf6" not in rest
    # current row = accent fill (one selection language)
    assert "#3182ce" in cur
    assert "QWidget:hover" in rest


def test_dropdown_status_text_qss_drops_amber():
    theme = {"text_secondary": "#e5e7eb", "button_text": "#ffffff"}
    cur = v2_style.dropdown_status_text_qss(theme, is_current=True)
    other = v2_style.dropdown_status_text_qss(theme, is_current=False)
    assert "#fbbf24" not in cur and "#fbbf24" not in other   # legacy amber gone
    assert "#ffffff" in cur                                   # current = button_text
    assert "#e5e7eb" in other                                 # else = text_secondary
    assert "font-weight: 700;" in cur


def test_dropdown_status_chip_qss_is_neutral():
    qss = v2_style.dropdown_status_chip_qss({"text_secondary": "#e5e7eb",
                                             "panel_alt_bg": "#1a202c", "border": "#2d3748"})
    assert "#1a202c" in qss                  # neutral panel, not green tint
    assert "rgba(5, 150, 105" not in qss     # legacy green wash gone
    assert "QLabel" in qss


def test_dropdown_status_defaults_are_safe():
    assert "QWidget" in v2_style.dropdown_status_row_qss({})
    assert "QLabel" in v2_style.dropdown_status_text_qss({})
    assert "QLabel" in v2_style.dropdown_status_chip_qss({})


def test_mic_control_qss_is_flat_ghost_with_semantic_role():
    theme = {"accent": "#3182ce", "danger": "#ef4444",
             "success": "#22c55e", "warning": "#f59e0b"}
    cancel = v2_style.mic_control_qss(theme, "danger")
    send = v2_style.mic_control_qss(theme, "primary")
    pause = v2_style.mic_control_qss(theme, "warning")
    # flat ghost: transparent rest, rounded, no heavy gradient fill at rest
    for qss in (cancel, send, pause):
        assert "background: transparent;" in qss
        assert "border-radius: 8px;" in qss
        assert "qlineargradient" not in qss
        assert "QPushButton:hover" in qss and "QPushButton:pressed" in qss
    # each keeps its semantic colour for hover border + pressed fill
    assert "#ef4444" in cancel
    assert "#22c55e" in send
    assert "#f59e0b" in pause
    # hover uses a soft rgba tint of that colour
    assert "rgba(239, 68, 68" in cancel


def test_mic_control_qss_defaults_are_safe():
    qss = v2_style.mic_control_qss({})
    assert "QPushButton" in qss
    assert "background: transparent;" in qss


def test_hex_to_rgba_parses_and_falls_back():
    assert v2_style._hex_to_rgba("#3182ce", 0.16) == "rgba(49, 130, 206, 0.16)"
    assert v2_style._hex_to_rgba("#fff", 0.5) == "rgba(255, 255, 255, 0.5)"
    # bad input falls back to accent blue, never raises
    assert "rgba(49, 130, 206" in v2_style._hex_to_rgba("nonsense", 0.2)


def test_clamp_popup_position_normal_anchor_unchanged():
    # popup fits on screen → stays at the anchor (just below the trigger)
    x, y = v2_style.clamp_popup_position(
        anchor_x=300, anchor_y=120, w=220, h=160,
        btn_top_y=80, avail_left=0, avail_top=0, avail_right=1920, avail_bottom=1080,
    )
    assert (x, y) == (300, 120)


def test_clamp_popup_position_clamps_right_edge():
    # anchored near the right edge → x pulled left so it stays on-screen
    x, y = v2_style.clamp_popup_position(
        anchor_x=1850, anchor_y=120, w=220, h=160,
        btn_top_y=80, avail_left=0, avail_top=0, avail_right=1920, avail_bottom=1080,
    )
    assert x == 1920 - 220 - 4
    assert y == 120


def test_clamp_popup_position_flips_above_on_bottom_overflow():
    # near the bottom → popup flips ABOVE the trigger (btn_top_y - h - gap)
    x, y = v2_style.clamp_popup_position(
        anchor_x=300, anchor_y=1040, w=220, h=300,
        btn_top_y=1000, avail_left=0, avail_top=0, avail_right=1920, avail_bottom=1080,
        gap_px=4,
    )
    assert y == 1000 - 300 - 4


def test_clamp_popup_position_never_off_top():
    # too tall to fit above OR below → clamped within the screen, never negative
    x, y = v2_style.clamp_popup_position(
        anchor_x=10, anchor_y=1070, w=200, h=1200,
        btn_top_y=1040, avail_left=0, avail_top=0, avail_right=1920, avail_bottom=1080,
    )
    assert y >= 4
