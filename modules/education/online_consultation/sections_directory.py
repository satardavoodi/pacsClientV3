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
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import assign_core, dashboard_core
from .profile_dialog import ConsultantProfileDialog as _SharedProfileDialog
from .sections_common import ConsultationSection

logger = logging.getLogger(__name__)


class ConsultantProfileDialog(_SharedProfileDialog):
    """Directory profile detail — the shared dialog (``profile_dialog``) with
    the "Request consultation…" entry point wired to this page (workflow v2:
    one ProfileDialog serves both the Directory and the Assign popup)."""

    def __init__(self, consultant: dict, page, parent=None):
        super().__init__(
            consultant, palette=page._p, parent=parent,
            request_callback=lambda c: page._assign_consultation(preselect=c),
        )
        self._page = page


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
        self._ext_ok = self._external_enabled()
        self._repopulate_specialties()
        self._apply_filters()

    def _external_enabled(self) -> bool:
        """Derived hub gate (owner directive 2026-06-11); fails OPEN."""
        try:
            from modules.cloud_consultation.ui.derived_status import (
                consultation_capabilities,
            )

            return bool(consultation_capabilities(
                self._page._aipacs_user())["external_enabled"])
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("external capability check failed (failing open): %s", exc)
            return True

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
        # Hub gate (owner directive 2026-06-11): without the AI-PACS Cloud Hub
        # external consultants render grayed/disabled with the reason; internal
        # consultants (and everything when the hub is available) are unchanged.
        ext_blocked = (d["kind"] == assign_core.EXTERNAL
                       and not getattr(self, "_ext_ok", True))
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        badge = QLabel(d["badge"])
        color = p["accent"] if d["kind"] == assign_core.INTERNAL else p["warning"]
        if ext_blocked:
            color = p["text_muted"]
        badge.setStyleSheet(
            f"color:{color};border:1px solid {color};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;"
        )
        lay.addWidget(badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(d["name"])
        name_color = p["text_muted"] if ext_blocked else p["text"]
        name.setStyleSheet(f"color:{name_color};font-size:13px;font-weight:500;")
        bits = [b for b in (d["specialty"], str(c.get("expertise") or ""),
                            d["availability"], d["address"]) if b]
        sub = QLabel(" · ".join(bits))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(name)
        col.addWidget(sub)
        if ext_blocked:
            reason = QLabel(assign_core.EXTERNAL_DISABLED_REASON)
            reason.setWordWrap(True)
            reason.setStyleSheet(
                f"color:{p['warning']};font-size:10px;font-style:italic;")
            col.addWidget(reason)
        lay.addLayout(col, 1)
        profile = QPushButton("Profile…")
        profile.clicked.connect(lambda _=False, cc=c: self._open_profile(cc))
        if ext_blocked:
            profile.setEnabled(False)
            profile.setToolTip(assign_core.EXTERNAL_DISABLED_REASON)
            f.setToolTip(assign_core.EXTERNAL_DISABLED_REASON)
        lay.addWidget(profile)
        return f

    def _open_profile(self, consultant: dict):
        try:
            ConsultantProfileDialog(consultant, self._page, parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("consultant profile dialog failed: %s", exc)
