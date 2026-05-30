"""Per-widget V2 styling helpers for the parallel AI-PACS design migration.

Each helper is **opt-in**: it is a no-op unless the relevant module's
``ui_variant`` is ``"v2"`` (default is ``"v1"``). Helpers build QSS from the
active theme tokens (never hard-coded hex) and **never raise** — on any error
the caller keeps its existing V1 style untouched. This is how Phase 2+ migrates
individual widgets without disturbing the live V1 UI. See
``docs/design/CLAUDE_DESIGN_WORKSTATION_V1_PLAN.md``.
"""
from __future__ import annotations

from PacsClient.utils.ui_variant import get_ui_variant


def home_is_v2() -> bool:
    """True only when the Home module is opted into the v2 design. Never raises."""
    try:
        return get_ui_variant("home") == "v2"
    except Exception:
        return False


def search_button_qss(theme: dict) -> str:
    """V2 QSS for the Home 'Search Patients' button.

    Renders Search as the page's single accent *primary* action (audit fix: it
    was an off-palette green). Pure function (takes a theme token dict) so it is
    unit-testable without Qt.
    """
    accent = theme.get("accent", "#3182ce")
    accent_hover = theme.get("accent_hover", accent)
    accent_pressed = theme.get("accent_pressed", accent)
    button_text = theme.get("button_text", "#ffffff")
    return (
        "QPushButton {\n"
        "    background: " + accent + ";\n"
        "    color: " + button_text + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "    border-radius: 8px;\n"
        "    padding: 8px 14px;\n"
        "    font-size: 13pt;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    margin: 0px;\n"
        "    letter-spacing: 0.5px;\n"
        "}\n"
        "QPushButton:hover {\n"
        "    background: " + accent_hover + ";\n"
        "    border-color: " + accent_hover + ";\n"
        "}\n"
        "QPushButton:pressed {\n"
        "    background: " + accent_pressed + ";\n"
        "    border-color: " + accent_pressed + ";\n"
        "}\n"
    )


def apply_search_button_v2(button) -> bool:
    """If Home is in v2, restyle ``button`` (the Search button) with accent tokens.

    Returns True if the v2 style was applied, False otherwise. Never raises; on
    any failure the button keeps whatever V1 style the caller already set.
    """
    try:
        if not home_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        theme = get_theme_manager().current_theme()
        button.setStyleSheet(search_button_qss(theme))
        return True
    except Exception:
        return False


def secondary_button_qss(theme: dict) -> str:
    """V2 QSS for a *secondary* (outline/ghost) button.

    Used to demote non-primary Home actions (e.g. "Adaptive to Screen Size",
    which was an off-palette purple) so the accent Search button reads as the
    single primary. Pure function (theme dict in) for testability.
    """
    border = theme.get("border", "#2d3748")
    text_secondary = theme.get("text_secondary", "#dbe7f3")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    accent = theme.get("accent", "#3182ce")
    return (
        "QPushButton {\n"
        "    background: transparent;\n"
        "    color: " + text_secondary + ";\n"
        "    border: 1px solid " + border + ";\n"
        "    border-radius: 8px;\n"
        "    padding: 6px 0px;\n"
        "    font-size: 13px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    margin: 0px;\n"
        "    text-align: center;\n"
        "}\n"
        "QPushButton:hover {\n"
        "    background: " + panel_alt + ";\n"
        "    border-color: " + accent + ";\n"
        "}\n"
    )


def table_header_qss(theme: dict) -> str:
    """V2 QSS for a data-table header (``QHeaderView::section``) from tokens.

    Replaces the hard-coded ``#1a202c`` header with ``menu_bg``/``text_secondary``/
    ``border`` so it tracks the active theme. Pure function for testability.
    """
    menu_bg = theme.get("menu_bg", "#223246")
    text_secondary = theme.get("text_secondary", "#dbe7f3")
    border = theme.get("border", "#2d3748")
    return (
        "QHeaderView::section {\n"
        "    background-color: " + menu_bg + ";\n"
        "    color: " + text_secondary + ";\n"
        "    padding: 8px;\n"
        "    border: 1px solid " + border + ";\n"
        "    font-weight: 600;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    text-align: center;\n"
        "    qproperty-alignment: AlignCenter;\n"
        "}\n"
    )


def apply_adaptive_button_v2(button) -> bool:
    """If Home is in v2, restyle a non-primary Home button as secondary. Never raises."""
    try:
        if not home_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        button.setStyleSheet(secondary_button_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def apply_table_header_v2(header) -> bool:
    """If Home is in v2, restyle a table header with token-based QSS. Never raises."""
    try:
        if not home_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        header.setStyleSheet(table_header_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def results_table_qss(theme: dict) -> str:
    """V2 QSS for the Home patient/worklist table: roomier rows and a softer
    accent selection (vs. the tight 2px padding + heavy solid-accent selection of
    V1). Pure function (theme dict in) for testability.
    """
    panel = theme.get("panel_bg", "#111927")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    border = theme.get("border", "#2d3748")
    text_primary = theme.get("text_primary", "#f8fafc")
    text_secondary = theme.get("text_secondary", "#dbe7f3")
    menu_bg = theme.get("menu_bg", "#223246")
    accent_soft = theme.get("accent_soft", theme.get("accent", "#3182ce"))
    return (
        "QTableWidget {\n"
        "    background: " + panel + ";\n"
        "    alternate-background-color: " + panel_alt + ";\n"
        "    gridline-color: transparent;\n"
        "    border: 1px solid " + border + ";\n"
        "    border-radius: 8px;\n"
        "}\n"
        "QTableWidget::item {\n"
        "    padding: 8px 10px;\n"
        "    border: none;\n"
        "    color: " + text_primary + ";\n"
        "}\n"
        "QTableWidget::item:selected {\n"
        "    background: " + accent_soft + ";\n"
        "    color: " + text_primary + ";\n"
        "}\n"
        "QHeaderView::section {\n"
        "    background: " + menu_bg + ";\n"
        "    color: " + text_secondary + ";\n"
        "    padding: 10px 8px;\n"
        "    border: none;\n"
        "    border-bottom: 1px solid " + border + ";\n"
        "    font-weight: 600;\n"
        "}\n"
    )


def apply_results_table_v2(table) -> bool:
    """If Home is in v2, give the patient table comfortable density + soft accent
    selection (and a roomier default row height). Never raises."""
    try:
        if not home_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        table.setStyleSheet(results_table_qss(get_theme_manager().current_theme()))
        try:
            table.verticalHeader().setDefaultSectionSize(38)
        except Exception:
            pass
        return True
    except Exception:
        return False


# --- Viewer module (Phase 3) -------------------------------------------------

def viewer_is_v2() -> bool:
    """True only when the Viewer module is opted into the v2 design. Never raises."""
    try:
        return get_ui_variant("viewer") == "v2"
    except Exception:
        return False


def thumbnail_header_qss(theme: dict) -> str:
    """V2 QSS for the viewer 'Series Thumbnails' header.

    Uses the real theme ``accent`` (flat) instead of the V1 purple fallback
    (``#7c3aed``) that leaks when the panel's cached theme lacks an accent.
    Pure function for testability.
    """
    accent = theme.get("accent", "#3182ce")
    button_text = theme.get("button_text", "#f7fafc")
    return (
        "QLabel {\n"
        "    font-size: 10px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    color: " + button_text + ";\n"
        "    padding: 6px 10px;\n"
        "    background: " + accent + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "    border-radius: 8px;\n"
        "}\n"
    )


def dropdown_panel_qss(theme: dict) -> str:
    """V2 dropdown/submenu panel: flat token surface, 1px border, rounded — to
    replace the old gradient + 2px border. Applied to the popup QWidget; its
    children (header, items) keep their own styles. Pure function."""
    panel = theme.get("card_bg", theme.get("panel_bg", "#111927"))
    border = theme.get("border", "#2d3748")
    return (
        "QWidget {\n"
        "    background: " + panel + ";\n"
        "    border: 1px solid " + border + ";\n"
        "    border-radius: 12px;\n"
        "}\n"
    )


def dropdown_header_qss(theme: dict) -> str:
    """V2 dropdown header: a quiet muted caption (not a filled accent bar), so it
    titles the menu without competing with the selection. Pure function."""
    text_muted = theme.get("text_muted", "#93a4b7")
    return (
        "QLabel {\n"
        "    color: " + text_muted + ";\n"
        "    font-size: 11px;\n"
        "    font-weight: 700;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    letter-spacing: 0.5px;\n"
        "    padding: 4px 8px 8px 8px;\n"
        "    background: transparent;\n"
        "    border: none;\n"
        "}\n"
    )


def apply_dropdown_panel_v2(dropdown) -> bool:
    """If Viewer is in v2, give a dropdown/submenu popup the flat V2 panel. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        dropdown.setStyleSheet(dropdown_panel_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def apply_dropdown_header_v2(label) -> bool:
    """If Viewer is in v2, restyle a dropdown header as a quiet caption. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        label.setStyleSheet(dropdown_header_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def dropdown_item_qss(theme: dict) -> str:
    """V2 dropdown/submenu ITEM row: a clean two-column layout — a fixed icon
    column then left-aligned text — so every icon sits at the same x and every
    label starts at the same x (no more centered, ragged rows). Achieved with
    ``qproperty-iconSize`` (one uniform icon size for the whole menu),
    ``text-align: left`` and a consistent left padding (the icon column). Flat
    ghost rest; ``accent_soft`` hover; ``accent`` selected. Pure function for
    testability."""
    text = theme.get("text_secondary", "#e5e7eb")
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", "#21314a")
    button_text = theme.get("button_text", "#ffffff")
    text_muted = theme.get("text_muted", "#93a4b7")
    return (
        "QPushButton {\n"
        "    qproperty-iconSize: 18px 18px;\n"   # one uniform icon column for all rows
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 8px;\n"
        "    text-align: left;\n"                # labels left-align, not centered
        "    padding: 7px 14px 7px 12px;\n"      # left pad = icon column; text follows fixed icon
        "    min-height: 20px;\n"                # ~34px uniform row height with padding
        "    font-size: 13px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    font-weight: 500;\n"
        "}\n"
        "QPushButton:hover {\n    background: " + accent_soft + ";\n    border: 1px solid " + accent + ";\n}\n"
        "QPushButton:pressed {\n    background: " + accent + ";\n    color: " + button_text + ";\n}\n"
        "QPushButton:checked {\n    background: " + accent + ";\n    color: " + button_text + ";\n    border: 1px solid " + accent + ";\n}\n"
        "QPushButton:disabled {\n    background: transparent;\n    color: " + text_muted + ";\n}\n"
    )


def apply_dropdown_item_v2(btn) -> bool:
    """If Viewer is in v2, give a dropdown/submenu item the two-column (icon column
    + left-aligned text) row style so all rows align. Applied from within
    ``_apply_dropdown_button_style`` so it survives re-styling. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(dropdown_item_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def dropdown_status_chip_qss(theme: dict) -> str:
    """Quiet 'Current Status:' chip — neutral panel surface instead of the legacy
    green tint. Pure function."""
    text = theme.get("text_secondary", "#e5e7eb")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    border = theme.get("border", "#2d3748")
    return (
        "QLabel {\n"
        "    color: " + text + ";\n"
        "    font-size: 11px;\n"
        "    font-weight: 600;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    background: " + panel_alt + ";\n"
        "    border: 1px solid " + border + ";\n"
        "    border-radius: 6px;\n"
        "    padding: 6px 10px;\n"
        "    margin-bottom: 8px;\n"
        "}\n"
    )


def dropdown_status_row_qss(theme: dict, is_current: bool = False) -> str:
    """Status row container in the V2 language: transparent rest, ``accent_soft``
    hover, ``accent`` fill when it is the current status — replacing the per-status
    coloured borders/gradients. The small status indicator dot (kept in the caller)
    still carries the colour semantics. Pure function for testability."""
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", "#21314a")
    if is_current:
        rest_bg = accent
        rest_border = accent
        hover_bg = accent
    else:
        rest_bg = "transparent"
        rest_border = "transparent"
        hover_bg = accent_soft
    return (
        "QWidget {\n"
        "    background: " + rest_bg + ";\n"
        "    border: 1px solid " + rest_border + ";\n"
        "    border-radius: 8px;\n"
        "}\n"
        "QWidget:hover {\n"
        "    background: " + hover_bg + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "}\n"
    )


def dropdown_status_text_qss(theme: dict, is_current: bool = False) -> str:
    """Status row label: neutral text (button_text when current, else
    text_secondary) instead of the legacy amber. Pure function."""
    button_text = theme.get("button_text", "#ffffff")
    text = theme.get("text_secondary", "#e5e7eb")
    color = button_text if is_current else text
    weight = "700" if is_current else "500"
    return (
        "QLabel {\n"
        "    color: " + color + ";\n"
        "    font-size: 12px;\n"
        "    font-weight: " + weight + ";\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    background: transparent;\n"
        "}\n"
    )


def apply_dropdown_status_chip_v2(label) -> bool:
    """If Viewer is in v2, quiet the 'Current Status:' chip. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        label.setStyleSheet(dropdown_status_chip_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def apply_dropdown_status_row_v2(container, is_current: bool = False) -> bool:
    """If Viewer is in v2, restyle a status row to the V2 language (transparent /
    accent_soft hover / accent when current). Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PySide6.QtCore import Qt
        from PacsClient.utils.theme_manager import get_theme_manager

        try:
            container.setAttribute(Qt.WA_StyledBackground, True)
        except Exception:
            pass
        container.setStyleSheet(dropdown_status_row_qss(get_theme_manager().current_theme(), is_current))
        return True
    except Exception:
        return False


def apply_dropdown_status_text_v2(label, is_current: bool = False) -> bool:
    """If Viewer is in v2, give a status row label the neutral V2 text. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        label.setStyleSheet(dropdown_status_text_qss(get_theme_manager().current_theme(), is_current))
        return True
    except Exception:
        return False


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Tiny hex -> rgba() helper so a semantic colour can tint a soft hover fill.
    Falls back to the accent blue on any parse error."""
    h = str(hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r, g, b = 49, 130, 206
    return "rgba(" + str(r) + ", " + str(g) + ", " + str(b) + ", " + str(alpha) + ")"


def mic_control_qss(theme: dict, role: str = "primary") -> str:
    """V2 style for an inline voice control (cancel / send / pause): a flat ghost
    button in the same interaction language as the toolbar — transparent rest, a
    soft tint of its semantic colour + that colour's border on hover, and a solid
    fill when pressed/active. ``role`` picks the semantic colour and keeps the
    affordance clear: ``danger`` = cancel (red), ``primary`` = send/finish
    (success green), ``warning`` = pause (amber). Uniform shape/radius/size across
    all three so they read as one first-class control group. Pure function."""
    accent = theme.get("accent", "#3182ce")
    danger = theme.get("danger", "#ef4444")
    success = theme.get("success", "#22c55e")
    warning = theme.get("warning", "#f59e0b")
    if role == "danger":
        c = danger
    elif role == "warning":
        c = warning
    elif role == "neutral":
        c = accent
    else:
        c = success
    soft = _hex_to_rgba(c, 0.16)
    return (
        "QPushButton {\n"
        "    background: transparent;\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 8px;\n"
        "    padding: 4px;\n"
        "    min-width: 30px;\n"
        "    min-height: 30px;\n"
        "    max-width: 30px;\n"
        "    max-height: 30px;\n"
        "}\n"
        "QPushButton:hover {\n    background: " + soft + ";\n    border: 1px solid " + c + ";\n}\n"
        "QPushButton:pressed {\n    background: " + c + ";\n}\n"
        "QPushButton:checked {\n    background: " + c + ";\n}\n"
    )


def apply_mic_control_v2(btn, role: str = "primary") -> bool:
    """If Viewer is in v2, give an inline voice control the flat V2 style for its
    ``role`` (danger/primary/warning). Applied after the legacy inline style so it
    overrides in v2 only. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(mic_control_qss(get_theme_manager().current_theme(), role))
        return True
    except Exception:
        return False


def clamp_popup_position(
    anchor_x: int, anchor_y: int, w: int, h: int,
    btn_top_y: int, avail_left: int, avail_top: int, avail_right: int, avail_bottom: int,
    gap_px: int = 4, margin: int = 4,
) -> tuple:
    """Compute a screen-clamped popup top-left.

    Anchors at (anchor_x, anchor_y) — the trigger's bottom-left plus ``gap_px`` — then:
      * horizontally clamps so the popup stays within [avail_left+margin, avail_right-margin],
      * if it would overflow the bottom, flips it ABOVE the trigger (``btn_top_y - h - gap_px``),
      * keeps the top within the screen.
    Pure function (no Qt) for testability."""
    x = int(anchor_x)
    y = int(anchor_y)
    if x + w > avail_right - margin:
        x = avail_right - w - margin
    if x < avail_left + margin:
        x = avail_left + margin
    if y + h > avail_bottom - margin:
        flipped = btn_top_y - h - gap_px
        if flipped >= avail_top + margin:
            y = flipped
        else:
            y = avail_bottom - h - margin
    if y < avail_top + margin:
        y = avail_top + margin
    return int(x), int(y)


def position_dropdown_v2(dropdown, button, gap_px: int = 4) -> bool:
    """If Viewer is in v2, re-anchor a frameless dropdown snugly under its trigger
    button (small ``gap_px``) and clamp it to the screen (flip above if it would run
    off the bottom). No-op in V1 (the caller's own ``.move()`` stands). Never raises.

    Call this right before ``dropdown.show()`` — after the popup's width/contents are
    set — so the size used for clamping is correct."""
    try:
        if not viewer_is_v2():
            return False
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication

        try:
            dropdown.adjustSize()
        except Exception:
            pass
        try:
            hint = dropdown.sizeHint()
            w = max(int(dropdown.width()), int(hint.width()))
            h = max(int(dropdown.height()), int(hint.height()))
        except Exception:
            w = int(dropdown.width())
            h = int(dropdown.height())

        anchor = button.mapToGlobal(QPoint(0, button.height() + int(gap_px)))
        btn_top = button.mapToGlobal(QPoint(0, 0))
        center = button.mapToGlobal(QPoint(button.width() // 2, button.height() // 2))
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is None:
            return False
        avail = screen.availableGeometry()
        x, y = clamp_popup_position(
            anchor.x(), anchor.y(), w, h, btn_top.y(),
            avail.left(), avail.top(), avail.right(), avail.bottom(),
            gap_px=int(gap_px),
        )
        dropdown.move(int(x), int(y))
        return True
    except Exception:
        return False


def badge_qss(theme: dict) -> str:
    """V2 QSS for a toolbar count badge: calm ``badge_blue`` (not the alarming
    red), flat, tight — a tidy notification pill instead of a big red gradient.
    Pure function for testability."""
    badge = theme.get("badge_blue", theme.get("accent", "#3182ce"))
    return (
        "QLabel {\n"
        "    background: " + badge + ";\n"
        "    color: #ffffff;\n"
        "    border: none;\n"
        "    border-radius: 7px;\n"
        "    padding: 0px 4px;\n"
        "    font-weight: 700;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "}\n"
    )


def apply_badge_v2(label) -> bool:
    """If Viewer is in v2, recolor a count badge to the calm accent/blue badge.
    Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        label.setStyleSheet(badge_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def apply_thumbnail_header_v2(label) -> bool:
    """If Viewer is in v2, restyle the 'Series Thumbnails' header with the real
    accent (fixes the off-palette purple). Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        label.setStyleSheet(thumbnail_header_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def tool_button_qss(theme: dict, w: int = 24, h: int = 24) -> str:
    """V2 QSS for a viewer toolbar button: a flat/ghost button (transparent until
    hover/active) instead of the heavy 3D-bevel accent block. Reduces the "16
    identical blue blocks" weight and lets the active tool stand out. Active
    (checked) = accent fill (vs. V1's green). Pure function for testability.
    """
    text = theme.get("text_secondary", "#e5e7eb")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", panel_alt)
    button_text = theme.get("button_text", "#ffffff")
    border = theme.get("border", "#2d3748")
    text_muted = theme.get("text_muted", "#93a4b7")
    return (
        "QPushButton {\n"
        "    qproperty-iconSize: " + str(w) + "px " + str(h) + "px;\n"
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 8px;\n"
        "    padding: 4px 6px;\n"
        "    margin: 2px 2px 0px 1px;\n"
        "    min-width: 40px;\n"
        "    min-height: 40px;\n"
        "    font-size: 13px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    font-weight: 500;\n"
        "}\n"
        "QPushButton:hover {\n"
        "    background: " + accent_soft + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "}\n"
        "QPushButton:pressed {\n"
        "    background: " + accent + ";\n"
        "    color: " + button_text + ";\n"
        "}\n"
        "QPushButton:checked {\n"
        "    background: " + accent + ";\n"
        "    color: " + button_text + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "}\n"
        "QPushButton:disabled {\n"
        "    background: transparent;\n"
        "    color: " + text_muted + ";\n"
        "}\n"
    )


def apply_tool_button_v2(btn, w: int = 24, h: int = 24) -> bool:
    """If Viewer is in v2, give a toolbar button the flat/ghost style. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(tool_button_qss(get_theme_manager().current_theme(), w, h))
        return True
    except Exception:
        return False


def qtoolbutton_qss(theme: dict) -> str:
    """V2 QSS for a viewer toolbar **QToolButton** (the actual main toolbar items).

    Same flat/ghost treatment as tool_button_qss but with QToolButton selectors
    (a QPushButton selector does not match a QToolButton). Pure function.
    """
    text = theme.get("text_secondary", "#e5e7eb")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", panel_alt)
    button_text = theme.get("button_text", "#ffffff")
    border = theme.get("border", "#2d3748")
    text_muted = theme.get("text_muted", "#93a4b7")
    return (
        "QToolButton {\n"
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: 8px;\n"
        "    padding: 4px 6px;\n"
        "    margin: 2px 2px 0px 1px;\n"
        "    min-width: 40px;\n"
        "    min-height: 40px;\n"
        "    font-size: 11px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    font-weight: 500;\n"
        "}\n"
        "QToolButton:hover {\n"
        "    background: " + accent_soft + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "}\n"
        "QToolButton:pressed {\n"
        "    background: " + accent + ";\n"
        "    color: " + button_text + ";\n"
        "}\n"
        "QToolButton:checked {\n"
        "    background: " + accent + ";\n"
        "    color: " + button_text + ";\n"
        "    border: 1px solid " + accent + ";\n"
        "}\n"
        "QToolButton:disabled {\n"
        "    background: transparent;\n"
        "    color: " + text_muted + ";\n"
        "}\n"
    )


def apply_qtoolbutton_v2(btn) -> bool:
    """If Viewer is in v2, give a QToolButton the flat/ghost style. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(qtoolbutton_qss(get_theme_manager().current_theme()))
        return True
    except Exception:
        return False


def pushbutton_ghost_qss(theme: dict, radius: str = "8px") -> str:
    """V2 flat/ghost QSS for a QPushButton toolbar item (dropdown / split-pair
    halves). ``radius`` lets split pairs keep their connected shape (e.g.
    '8px 0px 0px 8px' for the left half, '0px 8px 8px 0px' for the right).
    Pure function. No forced icon-size/width, so each button keeps its shape.
    """
    text = theme.get("text_secondary", "#e5e7eb")
    panel_alt = theme.get("panel_alt_bg", "#1a202c")
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", panel_alt)
    button_text = theme.get("button_text", "#ffffff")
    border = theme.get("border", "#2d3748")
    text_muted = theme.get("text_muted", "#93a4b7")
    return (
        "QPushButton {\n"
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: 1px solid transparent;\n"
        "    border-radius: " + radius + ";\n"
        "    padding: 6px 8px;\n"
        "    font-size: 12px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "    font-weight: 500;\n"
        "}\n"
        "QPushButton:hover {\n    background: " + accent_soft + ";\n    border: 1px solid " + accent + ";\n}\n"
        # groupHover: set by the split-pair event filter so BOTH halves highlight
        # together when either is hovered (unified hover).
        'QPushButton[groupHover="true"] {\n    background: ' + accent_soft + ";\n    border-color: " + accent + ";\n}\n"
        'QPushButton[groupHover="true"]:checked {\n    background: ' + accent + ";\n    color: " + button_text + ";\n}\n"
        "QPushButton:pressed {\n    background: " + accent + ";\n    color: " + button_text + ";\n}\n"
        "QPushButton:checked {\n    background: " + accent + ";\n    color: " + button_text + ";\n    border: 1px solid " + accent + ";\n}\n"
        "QPushButton:disabled {\n    background: transparent;\n    color: " + text_muted + ";\n}\n"
    )


def apply_pushbutton_ghost_v2(btn, radius: str = "8px") -> bool:
    """If Viewer is in v2, give a QPushButton toolbar item the flat/ghost style.
    ``radius`` preserves split-pair geometry. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(pushbutton_ghost_qss(get_theme_manager().current_theme(), radius))
        return True
    except Exception:
        return False


def split_container_hover_qss(theme: dict) -> str:
    """V2 container-level QSS that gives a split-button pair (hamburger ``split_left``
    + tool ``split_right``) ONE unified hover.

    Qt propagates ``:hover`` to a parent when the mouse is over any child, so a
    rule on the container highlights BOTH halves together (no event filters).
    The inner borders are dropped (left has no right border, right has no left
    border) so the two halves read as a single rounded rectangle. Active
    (``:checked``) halves keep the accent fill. Pure function for testability.
    """
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", accent)
    button_text = theme.get("button_text", "#ffffff")
    # Base highlight does NOT depend on property selectors and only recolors
    # (background + border-color) so each half keeps its width/border geometry —
    # when the container is hovered, BOTH child buttons highlight together.
    # The property-selector rules then drop the inner border for a seamless join.
    return (
        "QWidget:hover QPushButton { background: " + accent_soft + "; border-color: " + accent + "; }"
        'QWidget:hover QPushButton[_theme_style_type="split_left"] { border-right: none; }'
        'QWidget:hover QPushButton[_theme_style_type="split_right"] { border-left: none; }'
        'QWidget:hover QPushButton[_theme_style_type="split_right_danger"] { border-left: none; }'
        "QWidget:hover QPushButton:checked { background: " + accent + "; color: " + button_text + "; }"
    )


def split_inner_side_qss(theme: dict, side: str = "right") -> str:
    """One half of a split pair that draws its OWN box (rest transparent), with a
    width appropriate to its role: ``left`` = slim dropdown strip, ``right`` = the
    main tool area. Split geometry (left keeps left-rounded corners + drops its
    right border; right keeps right-rounded corners + drops its left border) so the
    two halves read as ONE rounded box. ``groupHover`` (set by the split-pair event
    filter on BOTH halves) gives the unified hover — hovering either half lights the
    whole pair. ``:checked`` = accent fill (selected tool). Drawing the box on the
    buttons (not the container) guarantees it paints. Pure function for testability."""
    text = theme.get("text_secondary", "#e5e7eb")
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", "#21314a")
    button_text = theme.get("button_text", "#ffffff")
    if side == "left":
        width = "    min-width: 16px;\n    max-width: 22px;\n"
        radius = (
            "    border-top-left-radius: 8px;\n    border-bottom-left-radius: 8px;\n"
            "    border-top-right-radius: 0px;\n    border-bottom-right-radius: 0px;\n"
        )
        drop = "    border-right: none;\n"
    else:
        width = "    min-width: 40px;\n"
        radius = (
            "    border-top-left-radius: 0px;\n    border-bottom-left-radius: 0px;\n"
            "    border-top-right-radius: 8px;\n    border-bottom-right-radius: 8px;\n"
        )
        drop = "    border-left: none;\n"
    return (
        "QPushButton {\n"
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: 1px solid transparent;\n"
        + drop
        + radius +
        "    padding: 4px 4px;\n"
        "    margin: 2px 0px 0px 0px;\n"
        + width +
        "    min-height: 40px;\n"
        "    font-family: 'Roboto', sans-serif;\n"
        "}\n"
        # Unified hover: the event filter sets groupHover on BOTH halves so the
        # whole pair lights together. A plain :hover fallback keeps at least the
        # touched half visible if the filter ever misses an event.
        'QPushButton[groupHover="true"] {\n    background: ' + accent_soft + ";\n    border: 1px solid " + accent + ";\n" + drop + "}\n"
        "QPushButton:hover {\n    background: " + accent_soft + ";\n    border: 1px solid " + accent + ";\n" + drop + "}\n"
        # Selected tool: accent fill (same look as a standalone checked button).
        "QPushButton:checked {\n    background: " + accent + ";\n    color: " + button_text + ";\n    border: 1px solid " + accent + ";\n" + drop + "}\n"
        'QPushButton[groupHover="true"]:checked {\n    background: ' + accent + ";\n    color: " + button_text + ";\n}\n"
        "QPushButton:pressed {\n    background: " + accent + ";\n    color: " + button_text + ";\n}\n"
        "QPushButton:disabled {\n    background: transparent;\n    border: 1px solid transparent;\n}\n"
    )


def apply_split_inner_v2(btn, side: str = "right") -> bool:
    """If Viewer is in v2, make a split half transparent (no box of its own).
    Applied from within ``_apply_split_*_style`` so it survives re-styling.
    Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PacsClient.utils.theme_manager import get_theme_manager

        btn.setStyleSheet(split_inner_side_qss(get_theme_manager().current_theme(), side))
        return True
    except Exception:
        return False


def split_box_qss(theme: dict) -> str:
    """The single 'box' for a split-button pair, drawn on the pair's CONTAINER so
    one border/background wraps BOTH halves (like a standalone toolbar button).
    Scoped via the ``v2box`` property so it never styles the inner buttons. Rest =
    transparent; groupHover = accent_soft tint + accent border; active = accent
    fill. Pure function for testability."""
    accent = theme.get("accent", "#3182ce")
    accent_soft = theme.get("accent_soft", accent)
    return (
        'QWidget[v2box="true"] { background: transparent; border: 1px solid transparent;'
        " border-radius: 8px; margin: 2px 2px 0px 1px; }"
        'QWidget[v2box="true"][groupHover="true"] { background: ' + accent_soft + "; border: 1px solid " + accent + "; }"
        'QWidget[v2box="true"][active="true"] { background: ' + accent + "; border: 1px solid " + accent + "; }"
    )


def split_inner_qss(theme: dict) -> str:
    """Inner half of a split pair: fully transparent (no box of its own) so only
    the container box shows. Keeps the icon centered; hover/active live on the
    container. Pure function for testability."""
    text = theme.get("text_secondary", "#e5e7eb")
    button_text = theme.get("button_text", "#ffffff")
    return (
        "QPushButton {\n"
        "    background: transparent;\n"
        "    color: " + text + ";\n"
        "    border: none;\n"
        "    border-radius: 0px;\n"
        "    padding: 4px 6px;\n"
        "    margin: 0px;\n"
        "    min-height: 40px;\n"
        "}\n"
        "QPushButton:checked { background: transparent; color: " + button_text + "; }\n"
        "QPushButton:disabled { background: transparent; }\n"
    )


_SPLIT_GROUP_CLS = None


def _split_group_cls():
    """Lazily define a QObject that unifies a split-button pair's hover: hovering
    either half sets ``groupHover=true`` on BOTH halves, so the whole pair lights
    as one box (selection rides on each button's native ``:checked``).
    Deterministic (does not rely on Qt's parent :hover). Defined lazily so this
    module imports without Qt for unit tests."""
    global _SPLIT_GROUP_CLS
    if _SPLIT_GROUP_CLS is None:
        from PySide6.QtCore import QObject, QEvent

        class _SplitGroup(QObject):
            def __init__(self, container, buttons):
                super().__init__(container)
                self._container = container
                self._buttons = list(buttons)
                self._inside = set()
                for b in self._buttons:
                    b.installEventFilter(self)

            def eventFilter(self, obj, ev):
                try:
                    t = ev.type()
                    if t == QEvent.Type.Enter:
                        self._inside.add(obj)
                        self._set("groupHover", True)
                    elif t == QEvent.Type.Leave:
                        self._inside.discard(obj)
                        self._set("groupHover", len(self._inside) > 0)
                except Exception:
                    pass
                return False

            def _set(self, name, value):
                # Drive the property on BOTH halves so the whole pair highlights as
                # one box (selection itself rides on each button's native :checked).
                value = bool(value)
                for w in self._buttons:
                    try:
                        if bool(w.property(name)) != value:
                            w.setProperty(name, value)
                            st = w.style()
                            st.unpolish(w)
                            st.polish(w)
                    except Exception:
                        pass

        _SPLIT_GROUP_CLS = _SplitGroup
    return _SPLIT_GROUP_CLS


def apply_split_hover_groups_v2(root) -> bool:
    """If Viewer is in v2, render each split-button pair as ONE compound control:
    a single container box (border/background/hover/active) around both halves,
    with the inner buttons transparent. Click targets are preserved (icon =
    action, hamburger = menu). Idempotent. Never raises."""
    try:
        if not viewer_is_v2():
            return False
        from PySide6.QtWidgets import QPushButton
        from PySide6.QtCore import Qt
        from PacsClient.utils.theme_manager import get_theme_manager

        theme = get_theme_manager().current_theme()
        box_qss = split_box_qss(theme)

        groups = {}
        for btn in root.findChildren(QPushButton):
            if btn.property("_theme_style_type") in ("split_left", "split_right", "split_right_danger"):
                container = btn.parentWidget()
                if container is not None:
                    groups.setdefault(container, []).append(btn)

        GroupCls = _split_group_cls()
        for container, buttons in groups.items():
            if len(buttons) < 2:
                continue
            # Only box a container dedicated to this pair (no other buttons), so a
            # shared toolbar row is never wrapped by mistake.
            if len(container.findChildren(QPushButton)) != len(buttons):
                continue
            container.setProperty("v2box", True)
            try:
                container.setAttribute(Qt.WA_StyledBackground, True)
            except Exception:
                pass
            container.setStyleSheet(box_qss)
            if not container.property("_v2_split_group_installed"):
                container.setProperty("_v2_split_group_installed", True)
                GroupCls(container, buttons)
        return True
    except Exception:
        return False
