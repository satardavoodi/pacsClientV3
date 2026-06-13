"""Shared read-only consultant profile dialog (assignment workflow v2).

ONE dialog for both entry points (owner spec, 2026-06-12):

* the Consultant Directory (``sections_directory``) — with the
  "Request consultation…" button (via ``request_callback``);
* the tabbed Assign popup (``assign_dialog``) — read-only "View profile".

It renders the same profile card data the directory uses: name / specialty /
expertise / availability / address / interests / resume / description, fed by
the ``GET /consultants`` row shape. Pure presentation — no network, no engine.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import assign_core

logger = logging.getLogger(__name__)

_FALLBACK_PALETTE = {
    "surface": "#0f172a", "surface2": "#1e293b", "border": "#334155",
    "text": "#e2e8f0", "text_muted": "#94a3b8", "accent": "#3b82f6",
    "accent_soft": "rgba(59,130,246,0.15)", "button_text": "#0b1220",
    "success": "#34d399", "warning": "#fbbf24", "danger": "#f87171",
}


def resolve_palette(palette: dict | None = None) -> dict:
    """The cloud-consultation theme palette, with a safe fallback."""
    if palette:
        return dict(palette)
    try:
        from modules.cloud_consultation.ui._theme import palette as _palette

        return dict(_palette())
    except Exception:  # pragma: no cover - defensive
        return dict(_FALLBACK_PALETTE)


class ConsultantProfileDialog(QDialog):
    """Read-only profile detail; optional "Request consultation…" affordance.

    ``request_callback(consultant)`` — when given, a primary button accepts the
    dialog and invokes it (the Directory wires it to the assign flow). Without
    it the dialog is purely informational (the Assign popup's View profile).
    """

    def __init__(self, consultant: dict, palette: dict | None = None,
                 parent=None, request_callback=None):
        super().__init__(parent)
        self._consultant = dict(consultant or {})
        self._request_callback = request_callback
        p = self._p = resolve_palette(palette)
        d = assign_core.consultant_display(self._consultant)
        self.setWindowTitle(f"Consultant — {d['name']}")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(8)

        head = QHBoxLayout()
        name = QLabel(d["name"])
        name.setStyleSheet(f"color:{p['text']};font-size:16px;font-weight:600;")
        head.addWidget(name, 1)
        badge = QLabel(d["badge"])
        color = p["accent"] if d["kind"] == assign_core.INTERNAL else p["warning"]
        badge.setStyleSheet(
            f"color:{color};border:1px solid {color};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;"
        )
        head.addWidget(badge, 0, Qt.AlignTop)
        root.addLayout(head)

        c = self._consultant
        for caption, value in (
            ("Specialty", d["specialty"]),
            ("Expertise", c.get("expertise")),
            ("Availability", d["availability"]),
            ("Consultation address", d["address"]),
            ("Interests", c.get("consultation_interests") or c.get("interests")),
            ("Background", c.get("resume_summary") or c.get("background")),
            ("About", c.get("description") or c.get("bio")),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            cap = QLabel(caption.upper())
            cap.setStyleSheet(
                f"color:{p['text_muted']};font-size:10px;font-weight:600;"
            )
            val = QLabel(text)
            val.setWordWrap(True)
            val.setStyleSheet(f"color:{p['text']};font-size:13px;")
            root.addWidget(cap)
            root.addWidget(val)

        root.addSpacing(6)
        btns = QHBoxLayout()
        btns.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        if callable(self._request_callback):
            request = QPushButton("Request consultation…")
            request.setObjectName("primary")
            request.clicked.connect(self._request)
            btns.addWidget(request)
        root.addLayout(btns)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:7px 14px; font-size:12px; }}
            QPushButton#primary {{ background:{p['accent']};
                color:{p['button_text']}; border:none; }}
            """
        )

    def _request(self):
        self.accept()
        try:
            self._request_callback(self._consultant)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("request consultation from profile failed: %s", exc)
