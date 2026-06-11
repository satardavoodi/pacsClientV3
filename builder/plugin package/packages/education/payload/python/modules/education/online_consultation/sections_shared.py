"""Shared Content section (ADR-0007 E) — read-only in v1.

Two lists from ``GET /education/shared``: items I shared (with their grants)
and items shared with me (with my capability), plus a note that consultation
Drive shares are managed automatically by the consultation lifecycle.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .sections_common import ConsultationSection

logger = logging.getLogger(__name__)


def _grant_text(grant: dict) -> str:
    g = grant or {}
    who = str(g.get("grantee_address") or g.get("grantee") or g.get("address")
              or "?").strip()
    cap = str(g.get("capability") or g.get("permission") or "view").strip()
    return f"{who} ({cap})"


class SharedSection(ConsultationSection):
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)
        scroll, self.listing = self.make_scroll_list()
        self._message_list = self.listing
        root.addWidget(scroll, 1)

    def _load(self):
        self.clear_list(self.listing)
        self.listing.insertWidget(0, self.muted_label("Loading shared content…"))
        self.start_worker(lambda client: client.shared_content(), self._on_data)

    def _on_data(self, data):
        data = data or {}
        self.clear_list(self.listing)
        idx = 0
        idx = self._insert(idx, self._caption("Shared by me"))
        by_me = list(data.get("shared_by_me") or [])
        if by_me:
            for item in by_me:
                idx = self._insert(idx, self._item_row(item, mine=True))
        else:
            idx = self._insert(idx, self.muted_label(
                "You have not shared any education content yet.", padding=4))
        idx = self._insert(idx, self._caption("Shared with me"))
        with_me = list(data.get("shared_with_me") or [])
        if with_me:
            for item in with_me:
                idx = self._insert(idx, self._item_row(item, mine=False))
        else:
            idx = self._insert(idx, self.muted_label(
                "Nothing has been shared with you yet.", padding=4))
        idx = self._insert(idx, self.muted_label(
            "Note: Drive access for consultation packages is granted and "
            "revoked automatically by the consultation lifecycle — those "
            "shares are not listed here.", padding=6))

    def _insert(self, idx: int, widget: QWidget) -> int:
        self.listing.insertWidget(idx, widget)
        return idx + 1

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{self._p['text_muted']};font-size:11px;font-weight:600;"
            f"padding-top:6px;")
        return lbl

    def _item_row(self, item: dict, *, mine: bool) -> QWidget:
        p = self._p
        item = item or {}
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        kind = str(item.get("kind") or item.get("type") or "item")
        chip = QLabel(kind.replace("_", " ").capitalize())
        chip.setStyleSheet(
            f"color:{p['accent']};border:1px solid {p['accent']};"
            f"border-radius:9px;padding:2px 9px;font-size:10px;font-weight:600;")
        lay.addWidget(chip)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(str(item.get("name") or item.get("title") or "(item)"))
        name.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:500;")
        col.addWidget(name)
        if mine:
            grants = [g for g in (item.get("grants") or []) if isinstance(g, dict)]
            text = ("Shared with: " + ", ".join(_grant_text(g) for g in grants)
                    if grants else "No active grants.")
        else:
            owner = str(item.get("owner_address") or item.get("owner") or "?")
            cap = str(item.get("capability") or item.get("permission") or "view")
            text = f"From {owner} · your access: {cap}"
        sub = QLabel(text)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(sub)
        lay.addLayout(col, 1)
        return f
