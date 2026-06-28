from __future__ import annotations

import os
import re
from html import unescape
from typing import Optional

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton

from .ai_chat_config import ICON_PATH

# ---- ICON helper ------------------------------------------------------------
def _set_icon(btn: QPushButton, name: str, size: int = 20, tooltip: str | None = None):
    try:
        btn.setIcon(QIcon(f"{ICON_PATH}/{name}"))
        btn.setIconSize(QSize(size, size))
        if tooltip is not None: btn.setToolTip(tooltip)
        btn.setText("")  
    except Exception:
        if tooltip and not btn.text(): btn.setText(tooltip)


# -----------------------------------------------------------------------------
def _safe_fa_connection_error(raw: str) -> str:
    s = "" if raw is None else str(raw)
    low = s.lower()

    # هر چیزی که عملاً شبکه/سرور/ DNS/ timeout باشد:
    network_markers = (
        "httpconnectionpool", "httpsconnectionpool",
        "max retries exceeded",
        "newconnectionerror", "nameresolutionerror",
        "failed to establish a new connection",
        "failed to resolve", "getaddrinfo failed",
        "connection refused", "actively refused",
        "unreachable host",
        "timed out", "timeout", "read timed out", "connecttimeout",
        "winerror 10061", "winerror 10065",
        "temporary failure in name resolution",
        "connectionerror",
        "ssl", "certificate verify failed",
    )

    if any(k in low for k in network_markers):
        return "❌ Error establishing a connection. Please check your internet connection and, if the issue persists, contact support."

    # برای بقیه خطاها هم (برای اینکه endpoint لو نرود) پیام عمومی بده:
    return "❌ Error establishing a connection. Please check your internet connection and, if the problem persists, contact support."

import re
from html import unescape

def extract_plain_text_from_html(html: str) -> str:
    """Convert (possibly Qt-rich) HTML into clean plain text.

    هدف:
      - استایل/رنگ/فونت/تگ‌ها به مدل ارسال نشود.
      - شکست خط‌ها تا حد ممکن حفظ شود (p/div/br/li/... → \n).
      - خروجی نهایی برای prompt مناسب باشد (trim + حذف خطوط خالی اضافی).
    """
    html = "" if html is None else str(html)
    if not html.strip():
        return ""

    # 1) Best effort: use Qt's HTML parser (handles qrichtext reliably)
    try:
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setHtml(html)
        txt = doc.toPlainText()
    except Exception:
        txt = html

    # 2) Fallback cleanup if Qt parse didn't run / left tags
    try:
        s = unescape(txt)
    except Exception:
        s = txt

    # If we still see tags, do a lightweight HTML→text conversion preserving newlines.
    if "<" in s and ">" in s:
        # remove script/style blocks
        s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", "\n", s)
        # structural breaks
        s = re.sub(r"(?is)<\s*br\s*/?>", "\n", s)
        s = re.sub(r"(?is)</\s*(p|div|tr|h\d|li)\s*>", "\n", s)
        # list items bullet-ish
        s = re.sub(r"(?is)<\s*li[^>]*>", "• ", s)
        # strip remaining tags
        s = re.sub(r"(?is)<[^>]+>", " ", s)

    # normalize spaces but keep newlines
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\xa0", " ").replace("&nbsp;", " ")
    s = re.sub(r"[ \t\f\v]+", " ", s)

    # trim each line and collapse multiple blank lines
    lines = [ln.strip() for ln in s.split("\n")]
    out_lines = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                out_lines.append("")
            continue
        blank = 0
        out_lines.append(ln)

    return "\n".join(out_lines).strip()


# -----------------------------------------------------------------------------
# Popup / dialog theming (readability fix, 2026-06-28)
# -----------------------------------------------------------------------------
# PROBLEM: several EchoMind popups (the "Select Reception ID" confirmation, the
# image-source picker, and every QMessageBox) set NO explicit colours, so they
# fall back to the Windows light/dark *system* palette — or worse, inherit the
# chat page's broad ``QWidget { background: transparent; }`` rule. On some
# machines that produced a near-white / transparent background with text the
# same shade as the background → unreadable confirmation text.
#
# FIX: give every popup an EXPLICIT, self-contained stylesheet that pairs each
# surface colour with its matching text colour from the active AI-PACS theme
# tokens. The result never depends on the OS theme and is identical on every
# computer running this build. Gated by ``AIPACS_ECHO_POPUP_THEME`` (default
# on); set it to ``0`` to restore the byte-identical legacy (unstyled) popups.

def _echo_popup_theme_enabled() -> bool:
    """Kill switch for the explicit popup theming (default ON)."""
    val = os.environ.get("AIPACS_ECHO_POPUP_THEME", "1").strip().lower()
    return val not in ("0", "false", "no", "off")


def popup_stylesheet() -> str:
    """Return a complete, theme-independent QSS for EchoMind popups/dialogs.

    Each surface (dialog, input, button) is paired with its matching text
    colour from the live AI-PACS theme tokens, so contrast is guaranteed and
    nothing inherits the Windows system palette. Safe to apply to a QDialog or
    a QMessageBox — the ``QMessageBox`` rules are inert on a plain dialog.
    """
    # Lazy import so this reflects the resolved theme tokens and never adds an
    # import-order constraint. Falls back to a known-good dark pair on error.
    try:
        from .ai_chat_config import (
            CLR_BG, CLR_BG_PANEL, CLR_TEXT, CLR_BORDER, CLR_ACCENT,
        )
    except Exception:  # pragma: no cover - defensive
        CLR_BG, CLR_BG_PANEL, CLR_TEXT, CLR_BORDER, CLR_ACCENT = (
            "#1b1b1b", "#222", "#f0f0f0", "#444", "#3182ce",
        )
    return f"""
        QDialog, QMessageBox {{
            background-color: {CLR_BG};
            color: {CLR_TEXT};
        }}
        QMessageBox QLabel, QDialog > QLabel, QLabel {{
            color: {CLR_TEXT};
            background: transparent;
        }}
        QLineEdit, QComboBox {{
            background-color: {CLR_BG_PANEL};
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            border-radius: 6px;
            padding: 5px 8px;
            selection-background-color: {CLR_ACCENT};
            selection-color: #ffffff;
        }}
        QComboBox QAbstractItemView {{
            background-color: {CLR_BG_PANEL};
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            selection-background-color: {CLR_ACCENT};
            selection-color: #ffffff;
        }}
        QPushButton {{
            background-color: {CLR_BG_PANEL};
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            border-radius: 7px;
            padding: 7px 14px;
            font-weight: 600;
            min-width: 72px;
        }}
        QPushButton:hover {{
            border-color: {CLR_ACCENT};
            background-color: rgba(255, 255, 255, 0.08);
        }}
        QPushButton:disabled {{
            color: rgba(220, 220, 220, 0.35);
            border-color: rgba(120, 120, 120, 0.35);
        }}
        QPushButton:default, QPushButton#ReceptionIdPrimaryButton {{
            background-color: {CLR_ACCENT};
            color: #ffffff;
            border: 1px solid {CLR_ACCENT};
        }}
        QPushButton:default:hover, QPushButton#ReceptionIdPrimaryButton:hover {{
            border-color: #ffffff;
        }}
    """


def style_popup(widget) -> None:
    """Apply the explicit popup stylesheet to a dialog/message box.

    No-op (legacy unstyled popup) when ``AIPACS_ECHO_POPUP_THEME`` is off or on
    any error — never raises into a clinical UI path.
    """
    if not _echo_popup_theme_enabled():
        return
    try:
        widget.setStyleSheet(popup_stylesheet())
    except Exception:
        pass


def themed_message_box(parent, icon, title, text, buttons=None, default=None):
    """Drop-in, explicitly-themed replacement for ``QMessageBox`` statics.

    Mirrors the semantics of ``QMessageBox.warning/information/critical/
    question`` exactly (same buttons, same default, same returned
    ``StandardButton``) but applies :func:`popup_stylesheet` so the text is
    always readable. When the kill switch is off it calls the original static
    method, preserving byte-identical legacy behaviour.
    """
    from PySide6.QtWidgets import QMessageBox

    if buttons is None:
        buttons = QMessageBox.StandardButton.Ok
    if default is None:
        default = QMessageBox.StandardButton.NoButton

    if not _echo_popup_theme_enabled():
        _legacy = {
            QMessageBox.Icon.Information: QMessageBox.information,
            QMessageBox.Icon.Warning: QMessageBox.warning,
            QMessageBox.Icon.Critical: QMessageBox.critical,
            QMessageBox.Icon.Question: QMessageBox.question,
        }.get(icon, QMessageBox.information)
        return _legacy(parent, title, text, buttons, default)

    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default != QMessageBox.StandardButton.NoButton:
        box.setDefaultButton(default)
    try:
        box.setStyleSheet(popup_stylesheet())
    except Exception:
        pass
    return box.exec()
