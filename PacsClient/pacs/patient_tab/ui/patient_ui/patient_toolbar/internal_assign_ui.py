# -*- coding: utf-8 -*-
"""Internal-assignment ENTRY POINT inside the Report Status popup.

This is only an **entry point** — it owns NO assignment logic. It shows a compact
summary of the current internal assignment and a button that opens THE shared
internal-assignment component:

    PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py
        → InternalAssignmentDialog / InternalAssignmentPanel

which is the exact same component the patient list's **Assign** column uses (the
consultation dialog's *Internal* tab embeds the same panel). One engine, one
form, one status model, one API path, one notification, one history — two entry
points.

History (2026-07-10): this file used to contain a SECOND, thinner implementation
of internal assignment (its own physicians-only combo, its own assign call with
no comment / no reassign flag, its own `notify_local_assignment`, and no
lifecycle actions). That divergence is the bug this refactor removes. Do NOT
reintroduce assignment logic here — extend the shared panel instead.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

logger = logging.getLogger("ino_assignment")


class InternalAssignRow(QWidget):
    """Summary + "manage" button. All behaviour lives in the shared panel."""

    def __init__(
        self,
        reception_id,
        assign_type: str = "radiologist",     # kept for call-site compatibility
        on_assigned: Optional[Callable[[str, str], None]] = None,
        patient_name: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._reception_id = str(reception_id)
        self._patient_name = str(patient_name or "")
        self._on_assigned = on_assigned
        self.setLayoutDirection(Qt.RightToLeft)
        self._build()
        self._refresh_summary()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(3)

        header = QLabel("ارجاع داخلی مرکز")
        header.setStyleSheet("color:#cfe0f5; font-weight:600;")
        root.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.current_label = QLabel("—")
        self.current_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
        self.manage_btn = QPushButton("مدیریت ارجاع…")
        self.manage_btn.setCursor(Qt.PointingHandCursor)
        self.manage_btn.clicked.connect(self._open_shared_component)
        row.addWidget(self.current_label, 1)
        row.addWidget(self.manage_btn)
        root.addLayout(row)

    # -- current assignment summary (read from the ONE persisted record) ----
    def _refresh_summary(self) -> None:
        name, status = "", ""
        try:
            from modules.network import ino_assignment_history as _h
            rec = _h.current_assignment_details(self._reception_id)
            if rec:
                name = str(rec.get("assignee_name") or "").strip()
                status = str(rec.get("assignment_status") or "").strip().lower()
        except Exception:  # pragma: no cover - defensive
            pass
        if not name:
            self.current_label.setText("ارجاع فعلی: —")
            self.current_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
            return
        try:
            from modules.network import ino_assignment_models as m
            label = m.status_label(status)
            color = m.status_color(status)
        except Exception:
            label, color = status.capitalize(), "#ef4444"
        suffix = f" ({label})" if label else ""
        self.current_label.setText(f"ارجاع فعلی: {name}{suffix}")
        self.current_label.setStyleSheet(
            f"color:{color}; font-size:11px; font-weight:600;")

    # -- open THE shared internal-assignment component -----------------------
    def _open_shared_component(self) -> None:
        try:
            from PacsClient.pacs.workstation_ui.home_ui.internal_assignment_panel import (
                open_internal_assignment_dialog,
            )
        except Exception:  # pragma: no cover - defensive
            logger.warning("[ino-assignment] shared panel unavailable", exc_info=True)
            return

        def _assigned(rid: str, name: str):
            self._refresh_summary()
            if self._on_assigned:
                try:
                    # Same callback contract the Report popup already expects.
                    self._on_assigned(name, str(rid))
                except Exception:
                    logger.exception("[ino-assignment] on_assigned callback failed")

        open_internal_assignment_dialog(
            self._reception_id, self._patient_name, parent=self, on_assigned=_assigned)
        self._refresh_summary()


def build_internal_assign_row(reception_id, on_assigned=None, parent=None,
                              patient_name: str = "") -> Optional[QWidget]:
    """Factory used by the Report Status popup. Returns the entry-point widget, or
    None when the feature is disabled / no reception id (popup unchanged)."""
    try:
        from PacsClient.pacs.workstation_ui.home_ui.internal_assignment_panel import (
            internal_assignment_available,
        )
        if not internal_assignment_available(reception_id):
            return None
        return InternalAssignRow(reception_id, on_assigned=on_assigned,
                                 patient_name=patient_name, parent=parent)
    except Exception:
        logger.warning("[ino-assignment] could not build assign row", exc_info=True)
        return None
