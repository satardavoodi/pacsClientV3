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


# ─────────────────────────────────────────────────────────────────────────────
# EchoMind user-facing error text  (F2, 2026-07-28)
#
# THE DEFECT THIS REPLACES: both return branches of the old
# ``_safe_fa_connection_error`` emitted the SAME sentence ("check your internet
# connection") — they differed only by the word *issue* vs *problem*. Every
# exception escaping an ``ApiWorker`` ``work()`` closure is routed through here
# (``ai_chat_api.py`` ``ApiWorker.run``), so the rich, actionable errors
# ``llm_client.py`` already raises — ``LLMNoKeyError`` ("No OpenAI API key is
# configured"), ``LLMAuthError`` ("<provider> rejected the request"),
# ``LLMAPIError`` ("<provider> HTTP 429: …") — were all flattened into a network
# complaint. A physician whose key expired, whose quota ran out, or who typed a
# model name the provider does not serve was told to check their internet.
#
# THE RULE: **redacting the endpoint must not cost us the diagnosis.** Hiding a
# host name and reporting "HTTP 401 — the server rejected the configured API
# key" are independent goals; the old code sacrificed the second to achieve the
# first. Every branch below still passes its text through
# ``_redact_endpoint_details``, so no URL, IP:port, bearer token or ``sk-…`` key
# can reach the UI — that property is preserved and unit-tested.
#
# The NETWORK branch is deliberately byte-identical to the legacy sentence (same
# marker list, same text), because that message was correct for that case.
# Only the previously-indistinguishable *other* half is classified.
#
# Flag ``AIPACS_ECHOMIND_ERROR_DETAIL`` (default ON). ``=0`` restores the
# byte-identical legacy two-branch behaviour.
# ─────────────────────────────────────────────────────────────────────────────

_ENV_ERROR_DETAIL = "AIPACS_ECHOMIND_ERROR_DETAIL"

#: Legacy list — UNCHANGED. Anything matching still gets the legacy sentence.
_NETWORK_MARKERS = (
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

_LEGACY_NETWORK_TEXT = (
    "❌ Error establishing a connection. Please check your internet connection "
    "and, if the issue persists, contact support."
)
_LEGACY_FALLBACK_TEXT = (
    "❌ Error establishing a connection. Please check your internet connection "
    "and, if the problem persists, contact support."
)

# Raised by llm_client before any request is made — unambiguous, check first.
_NO_KEY_MARKERS = (
    "no echomind credential",
    "no openai api key",
    "no gapgpt key",
    "api key is not configured",
    "api key cannot be empty",
    "backend is not configured",
    "no validated irannobat api key",
    "no usable backend key",
)

_AUTH_MARKERS = (
    "rejected the request",
    "authentication failed",
    "invalid api key",
    "invalid_api_key",
    "incorrect api key",
    "unauthorized",
    "invalid center api key",
    "invalid authentication",
)

_QUOTA_MARKERS = (
    "insufficient_quota",
    "rate limit",
    "rate_limit",
    "exceeded your current quota",
    "billing",
)

# Deliberately NARROW. A loose marker like "the model" would swallow ordinary
# server prose and mislabel unrelated failures as a model-configuration problem.
_MODEL_MARKERS = (
    "model_not_found",
    "does not exist or you do not have access",
    "unknown model",
    "invalid model",
    "unsupported model",
    "no such model",
)

_MALFORMED_MARKERS = (
    "malformed response",
    "no assistant content",
    "missing choices",
    "expecting value",
)

# "<provider> HTTP 429: ..."  /  "status=500"  /  "401 Client Error: ..."
_HTTP_STATUS_RE = re.compile(r"(?:\bhttp[ _]?|\bstatus[ =:]+)(\d{3})\b", re.I)
_CLIENT_ERR_RE = re.compile(r"\b(\d{3})\s+(?:client|server)\s+error\b", re.I)

# Redaction — nothing that identifies a server or a credential may reach the UI.
_URL_RE = re.compile(r"https?://[^\s'\"<>)\]}]+", re.I)
_HOSTPORT_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_APIKEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}", re.I)
_BEARER_RE = re.compile(r"\bbearer\s+\S+", re.I)


def error_detail_enabled() -> bool:
    """Kill switch. ``0`` = legacy two-branch behaviour (byte-identical)."""
    raw = os.environ.get(_ENV_ERROR_DETAIL)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _redact_endpoint_details(text: str, limit: int = 200) -> str:
    """Strip every server address / credential, collapse whitespace, truncate.

    This is the property the legacy function existed to guarantee, and it is
    applied to EVERY string this module hands to the UI — including the new
    classified branches. Never returns a URL, an IP:port, a bearer token or an
    ``sk-…`` key.
    """
    s = str(text or "")
    s = _URL_RE.sub("<server>", s)
    s = _HOSTPORT_RE.sub("<host>", s)
    s = _BEARER_RE.sub("Bearer <key>", s)
    s = _APIKEY_RE.sub("<key>", s)
    s = " ".join(s.split())
    return s[:limit].strip()


def _http_status_in(text: str) -> "int | None":
    """The HTTP status llm_client/requests embedded in the message, if any."""
    for rx in (_CLIENT_ERR_RE, _HTTP_STATUS_RE):
        m = rx.search(text or "")
        if not m:
            continue
        try:
            code = int(m.group(1))
        except Exception:
            continue
        if 100 <= code <= 599:
            return code
    return None


def classify_echomind_error(raw: str) -> "tuple[str, str]":
    """``(kind, user_text)`` for an EchoMind failure. Pure — no Qt, no network.

    ``kind`` is one of: ``no_key``, ``auth``, ``quota``, ``model``,
    ``server``, ``bad_request``, ``malformed``, ``network``, ``unknown``.
    It exists so callers/tests can assert the classification without matching
    on display text.
    """
    s = "" if raw is None else str(raw)
    low = s.lower()
    detail = _redact_endpoint_details(s)

    # 1) No credential at all — raised before any request leaves the machine.
    if any(k in low for k in _NO_KEY_MARKERS):
        return "no_key", (
            "❌ No AI credential is configured. Open Settings ▸ EchoMind and "
            "authenticate (or enter an OpenAI API key) before using this feature."
        )

    # 2) An explicit HTTP status — the most reliable signal we have, and the
    #    shape llm_client itself formats ("<provider> HTTP 401: …").
    status = _http_status_in(s)
    if status is not None:
        if status in (401, 403):
            return "auth", (
                f"❌ The AI server rejected the credential (HTTP {status}). "
                "Check the API key in Settings ▸ EchoMind — it may be wrong, "
                "expired, or not permitted for this model."
            )
        if status == 429:
            return "quota", (
                "❌ The AI server refused the request (HTTP 429): rate limit or "
                "quota exceeded. Wait a moment and retry, or check the plan/"
                "billing for this key."
            )
        if status == 404:
            return "model", (
                "❌ The AI server could not find the requested resource "
                "(HTTP 404). The configured model name may not exist on this "
                "provider — check Settings ▸ EchoMind ▸ models."
            )
        if 500 <= status <= 599:
            return "server", (
                f"❌ The AI server reported an internal error (HTTP {status}). "
                "This is on the server side — retry shortly; if it persists, "
                f"contact support.\n\nDetail: {detail}"
            )
        if 400 <= status <= 499:
            return "bad_request", (
                f"❌ The AI server refused the request (HTTP {status}).\n\n"
                f"Detail: {detail}"
            )

    # 3) Text-only auth / quota / model signals (providers word these freely).
    if any(k in low for k in _AUTH_MARKERS):
        return "auth", (
            "❌ The AI server rejected the credential. Check the API key in "
            "Settings ▸ EchoMind — it may be wrong, expired, or not permitted "
            "for this model."
        )
    if any(k in low for k in _QUOTA_MARKERS):
        return "quota", (
            "❌ The AI request was refused: rate limit or quota exceeded. Wait a "
            "moment and retry, or check the plan/billing for this key."
        )
    if any(k in low for k in _MODEL_MARKERS):
        return "model", (
            "❌ The configured model is not available on this provider. Check "
            "Settings ▸ EchoMind ▸ models.\n\n"
            f"Detail: {detail}"
        )

    # 4) We reached the server but could not read what came back.
    if any(k in low for k in _MALFORMED_MARKERS):
        return "malformed", (
            "❌ The AI server replied with something EchoMind could not read. "
            "This usually means the server or the selected model returned an "
            f"unexpected format.\n\nDetail: {detail}"
        )

    # 5) Genuine transport failure — legacy text, unchanged.
    if any(k in low for k in _NETWORK_MARKERS):
        return "network", _LEGACY_NETWORK_TEXT

    # 6) Anything else: say so honestly instead of blaming the network.
    if detail:
        return "unknown", f"❌ The AI request failed.\n\nDetail: {detail}"
    return "unknown", "❌ The AI request failed."


# -----------------------------------------------------------------------------
def _safe_fa_connection_error(raw: str) -> str:
    """User-facing text for a failed EchoMind request (endpoint always redacted)."""
    if not error_detail_enabled():
        # Legacy path — byte-identical to the pre-2026-07-28 behaviour.
        s = "" if raw is None else str(raw)
        low = s.lower()
        if any(k in low for k in _NETWORK_MARKERS):
            return _LEGACY_NETWORK_TEXT
        return _LEGACY_FALLBACK_TEXT

    try:
        return classify_echomind_error(raw)[1]
    except Exception:
        # This function sits on the failure path — it must never raise.
        return _LEGACY_FALLBACK_TEXT

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
        QTextEdit, QPlainTextEdit, QTextBrowser {{
            background-color: {CLR_BG_PANEL};
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            border-radius: 6px;
            selection-background-color: {CLR_ACCENT};
            selection-color: #ffffff;
        }}
        QMenu {{
            background-color: {CLR_BG_PANEL};
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
        }}
        QMenu::item {{
            background: transparent;
            color: {CLR_TEXT};
            padding: 5px 24px;
        }}
        QMenu::item:selected {{
            background-color: {CLR_ACCENT};
            color: #ffffff;
        }}
        QMenu::item:disabled {{
            color: rgba(220, 220, 220, 0.35);
        }}
        QMenu::separator {{
            height: 1px;
            background: {CLR_BORDER};
            margin: 4px 8px;
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


def themed_input_text(parent, title, label, text="", echo=None):
    """Drop-in, explicitly-themed replacement for ``QInputDialog.getText``.

    Returns ``(value: str, ok: bool)`` exactly like the static method, but the
    input dialog carries the explicit popup colours so the prompt and field are
    readable on any Windows theme. Falls back to the static call when the kill
    switch is off.
    """
    from PySide6.QtWidgets import QInputDialog, QLineEdit

    if echo is None:
        echo = QLineEdit.EchoMode.Normal

    if not _echo_popup_theme_enabled():
        return QInputDialog.getText(parent, title, label, echo, text)

    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    try:
        dlg.setTextEchoMode(echo)
    except Exception:
        pass
    dlg.setTextValue(text)
    try:
        dlg.setStyleSheet(popup_stylesheet())
    except Exception:
        pass
    ok = bool(dlg.exec())
    return dlg.textValue(), ok
