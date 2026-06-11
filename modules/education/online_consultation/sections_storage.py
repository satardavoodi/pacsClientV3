"""Storage & Usage section (ADR-0007 D).

Cards (total / used / remaining) from ``/me/storage``, per-category bars +
largest folders + cleanup candidates from ``/me/storage/breakdown``. Laravel
stays the storage authority (ADR-0005) — this view is read-only: cleanup
candidates only offer an "Open folder in Drive" link, NO delete action in v1
(deletion is a future, deliberate feature).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import dashboard_core
from .sections_common import ConsultationSection

logger = logging.getLogger(__name__)

_CATEGORY_LABELS = (
    ("consultations", "Consultations"),
    ("case_of_day", "Case of the Day"),
    ("course", "Courses"),
    ("other", "Other"),
)


def drive_folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


class StorageSection(ConsultationSection):
    def _build(self):
        self._loaded_at = None  # time.monotonic() of the last successful load
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)
        scroll, self.listing = self.make_scroll_list()
        self._message_list = self.listing
        root.addWidget(scroll, 1)

    def activate(self):
        """ADR-0007 D: reuse the rendered result on re-entry within 5 min;
        refetch when the client-side timestamp has gone stale."""
        if not self._loaded:
            self.refresh()
            return
        if not dashboard_core.storage_cache_fresh(self._loaded_at):
            self.refresh()

    def _load(self):
        self.clear_list(self.listing)
        self.listing.insertWidget(0, self.muted_label("Loading storage usage…"))
        self.start_worker(
            lambda client: {
                "storage": client.my_storage() or {},
                "breakdown": client.storage_breakdown() or {},
            },
            self._on_data,
        )

    # ── render ────────────────────────────────────────────────────────────────
    def _on_data(self, data):
        import time

        self._loaded_at = time.monotonic()
        data = data or {}
        storage = data.get("storage") or {}
        breakdown = data.get("breakdown") or {}
        self.clear_list(self.listing)
        idx = 0

        idx = self._insert(idx, self._cards_row(storage))
        bars = self._category_bars(breakdown)
        if bars is not None:
            idx = self._insert(idx, self._caption("Usage by category"))
            idx = self._insert(idx, bars)
        largest = list(breakdown.get("largest_folders") or [])
        if largest:
            idx = self._insert(idx, self._caption("Largest folders"))
            for item in largest:
                idx = self._insert(idx, self._folder_row(item))
        candidates = list(breakdown.get("cleanup_candidates") or [])
        idx = self._insert(idx, self._caption("Cleanup candidates"))
        if candidates:
            note = self.muted_label(
                "Closed or stale consultation folders you may want to clean up. "
                "Review them in Drive — nothing is ever deleted from here.",
                padding=4)
            idx = self._insert(idx, note)
            for item in candidates:
                idx = self._insert(idx, self._candidate_row(item))
        else:
            idx = self._insert(idx, self.muted_label(
                "No cleanup candidates — nothing closed or stale.", padding=4))

    def _insert(self, idx: int, widget: QWidget) -> int:
        self.listing.insertWidget(idx, widget)
        return idx + 1

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{self._p['text_muted']};font-size:11px;font-weight:600;"
            f"padding-top:6px;")
        return lbl

    def _cards_row(self, storage: dict) -> QWidget:
        p = self._p
        summary = dashboard_core.storage_summary(storage)
        quota, used = summary["quota"], summary["used"]
        remaining = (quota - used) if (quota is not None and used is not None) else None
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        fmt = dashboard_core.format_bytes
        used_color = p["warning"] if summary["warn"] else p["text"]
        for caption, value, color in (
            ("Total quota", fmt(quota) if quota is not None else "—", p["text"]),
            ("Used", fmt(used) if used is not None else "—", used_color),
            ("Remaining", fmt(remaining) if remaining is not None else "—",
             p["success"]),
        ):
            card = self.card()
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(1)
            num = QLabel(value)
            num.setStyleSheet(f"color:{color};font-size:18px;font-weight:600;")
            cap = QLabel(caption)
            cap.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            v.addWidget(num)
            v.addWidget(cap)
            row.addWidget(card, 1)
        return host

    def _category_bars(self, breakdown: dict) -> QWidget | None:
        p = self._p
        cats = breakdown.get("breakdown")
        if not isinstance(cats, dict) or not cats:
            return None
        total = dashboard_core._first_int(breakdown, ("total_bytes",)) or 0
        denom = max(total, sum(int(cats.get(k) or 0)
                               for k, _lbl in _CATEGORY_LABELS), 1)
        host = self.card()
        v = QVBoxLayout(host)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        for key, label in _CATEGORY_LABELS:
            value = int(cats.get(key) or 0)
            row = QHBoxLayout()
            cap = QLabel(label)
            cap.setFixedWidth(120)
            cap.setStyleSheet(f"color:{p['text']};font-size:12px;")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(round(1000 * value / denom)))
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar{{background:{p['surface']};border:1px solid "
                f"{p['border']};border-radius:4px;}}"
                f"QProgressBar::chunk{{background:{p['accent']};border-radius:4px;}}"
            )
            size = QLabel(dashboard_core.format_bytes(value))
            size.setFixedWidth(80)
            size.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            row.addWidget(cap)
            row.addWidget(bar, 1)
            row.addWidget(size)
            v.addLayout(row)
        return host

    def _folder_row(self, item: dict) -> QWidget:
        p = self._p
        item = item or {}
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        name = QLabel(str(item.get("name") or "(folder)"))
        name.setStyleSheet(f"color:{p['text']};font-size:12px;")
        kind = QLabel(str(item.get("kind") or ""))
        kind.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        size = QLabel(dashboard_core.format_bytes(item.get("bytes")))
        size.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        lay.addWidget(name, 1)
        lay.addWidget(kind)
        lay.addWidget(size)
        self._add_drive_link(lay, item)
        return f

    def _candidate_row(self, item: dict) -> QWidget:
        p = self._p
        item = item or {}
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        reason = str(item.get("reason") or "stale")
        chip = QLabel(reason.capitalize())
        color = p["text_muted"] if reason == "closed" else p["warning"]
        chip.setStyleSheet(
            f"color:{color};border:1px solid {color};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;")
        lay.addWidget(chip)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(str(item.get("name") or item.get("consultation_id")
                          or "(consultation)"))
        name.setStyleSheet(f"color:{p['text']};font-size:12px;")
        bits = [dashboard_core.format_bytes(item.get("bytes"))]
        if item.get("modified_time"):
            bits.append(f"modified {item.get('modified_time')}")
        sub = QLabel(" · ".join(bits))
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        self._add_drive_link(lay, item)
        return f

    def _add_drive_link(self, lay, item: dict):
        folder_id = str((item or {}).get("id") or "").strip()
        if not folder_id:
            return
        btn = QPushButton("Open folder in Drive")
        btn.clicked.connect(
            lambda _=False, fid=folder_id: self._open_drive(fid))
        lay.addWidget(btn)

    @staticmethod
    def _open_drive(folder_id: str):
        try:
            QDesktopServices.openUrl(QUrl(drive_folder_url(folder_id)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("open drive folder failed: %s", exc)
