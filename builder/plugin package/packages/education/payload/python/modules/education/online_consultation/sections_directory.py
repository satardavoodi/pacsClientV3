"""Consultant Directory section (ADR-0007 A).

Browse / search / filter the consultant roster (client-side filtering via the
Qt-free :mod:`dashboard_core`), open a full profile, and start the existing
assign flow with that consultant preselected.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import assign_core, dashboard_core
from .sections_common import ConsultationSection

logger = logging.getLogger(__name__)


class ConsultantProfileDialog(QDialog):
    """Read-only profile detail with a "Request consultation…" entry point."""

    def __init__(self, consultant: dict, page, parent=None):
        super().__init__(parent)
        self._consultant = dict(consultant or {})
        self._page = page
        p = page._p
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
        request = QPushButton("Request consultation…")
        request.setObjectName("primary")
        request.clicked.connect(self._request)
        btns.addWidget(close)
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
            self._page._assign_consultation(preselect=self._consultant)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("request consultation from profile failed: %s", exc)


class DirectorySection(ConsultationSection):
    """Roster list + search box + type/availability filters (ADR-0007 A)."""

    def _build(self):
        p = self._p
        self._consultants: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setContentsMargins(10, 0, 10, 0)
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, specialty, expertise…")
        self.search.textChanged.connect(self._apply_filters)
        self.search.setStyleSheet(
            f"background:{p['surface2']};color:{p['text']};border:1px solid "
            f"{p['border']};border-radius:8px;padding:6px 10px;font-size:12px;"
        )
        bar.addWidget(self.search, 1)
        self.kind_filter = QComboBox()
        self.kind_filter.addItems(["All types", "Internal", "External"])
        self.kind_filter.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self.kind_filter)
        self.specialty_filter = QComboBox()
        self.specialty_filter.addItem("All specialties")
        self.specialty_filter.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self.specialty_filter)
        self.avail_filter = QComboBox()
        self.avail_filter.addItem("Any availability")
        for v in dashboard_core.AVAILABILITY_VALUES:
            self.avail_filter.addItem(v.capitalize())
        self.avail_filter.currentIndexChanged.connect(self._apply_filters)
        bar.addWidget(self.avail_filter)
        root.addLayout(bar)

        scroll, self.listing = self.make_scroll_list()
        self._message_list = self.listing
        root.addWidget(scroll, 1)

    def _load(self):
        self.clear_list(self.listing)
        self.listing.insertWidget(0, self.muted_label("Loading consultants…"))
        self.start_worker(lambda client: list(client.consultants()),
                          self._on_consultants)

    def _on_consultants(self, rows):
        self._consultants = list(rows or [])
        self._repopulate_specialties()
        self._apply_filters()

    def _repopulate_specialties(self):
        """Refill the specialty combo from the roster, keeping the selection."""
        try:
            current = self.specialty_filter.currentText()
            self.specialty_filter.blockSignals(True)
            self.specialty_filter.clear()
            self.specialty_filter.addItem("All specialties")
            for spec in dashboard_core.consultant_specialties(self._consultants):
                self.specialty_filter.addItem(spec)
            idx = self.specialty_filter.findText(current)
            self.specialty_filter.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self.specialty_filter.blockSignals(False)

    # ── filtering / rendering ─────────────────────────────────────────────────
    def _filter_args(self):
        kind = ("all", assign_core.INTERNAL, assign_core.EXTERNAL)[
            max(0, self.kind_filter.currentIndex())]
        idx = self.avail_filter.currentIndex()
        availability = ("all", *dashboard_core.AVAILABILITY_VALUES)[max(0, idx)] \
            if idx < 1 + len(dashboard_core.AVAILABILITY_VALUES) else "all"
        specialty = ("all" if self.specialty_filter.currentIndex() <= 0
                     else self.specialty_filter.currentText())
        return {"query": self.search.text(), "kind": kind,
                "availability": availability, "specialty": specialty}

    def _apply_filters(self, *_args):
        self.clear_list(self.listing)
        rows = dashboard_core.filter_consultants(
            self._consultants, **self._filter_args())
        if not rows:
            text = ("No consultants are available yet."
                    if not self._consultants else
                    "No consultant matches the current filters.")
            self.listing.insertWidget(0, self.muted_label(text))
            return
        for c in rows:
            self.listing.insertWidget(self.listing.count() - 1, self._card(c))

    def _card(self, c: dict) -> QWidget:
        p = self._p
        d = assign_core.consultant_display(c)
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        badge = QLabel(d["badge"])
        color = p["accent"] if d["kind"] == assign_core.INTERNAL else p["warning"]
        badge.setStyleSheet(
            f"color:{color};border:1px solid {color};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;"
        )
        lay.addWidget(badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(d["name"])
        name.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        bits = [b for b in (d["specialty"], str(c.get("expertise") or ""),
                            d["availability"], d["address"]) if b]
        sub = QLabel(" · ".join(bits))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        profile = QPushButton("Profile…")
        profile.clicked.connect(lambda _=False, cc=c: self._open_profile(cc))
        lay.addWidget(profile)
        return f

    def _open_profile(self, consultant: dict):
        try:
            ConsultantProfileDialog(consultant, self._page, parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("consultant profile dialog failed: %s", exc)
