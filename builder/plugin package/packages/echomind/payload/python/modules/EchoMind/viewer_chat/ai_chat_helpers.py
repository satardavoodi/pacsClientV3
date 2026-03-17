from __future__ import annotations

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
