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

    # -- current assignment summary (the SAME merged view the Assign column uses) --
    def _refresh_summary(self) -> None:
        """Show the assignment from the SERVER, exactly like the Assign column.

        2026-07-14 — this used to read ``ino_assignment_history`` (the LOCAL action
        log), so the Report popup showed nothing for a reception assigned on ANOTHER
        workstation while the Assign popup (which already reads the merged view)
        showed it correctly. That is precisely the "the Assign popup works, the
        Report popup does not" report. Both entry points now call the ONE accessor,
        ``ino_assignment_details.get_assignment_details``, so they cannot diverge
        again.
        """
        rec = None
        try:
            from modules.network import ino_assignment_details as _d
            rec = _d.get_assignment_details(self._reception_id)
        except Exception:  # pragma: no cover - defensive
            rec = None

        name = str((rec or {}).get("assignee_name") or "").strip()
        status = str((rec or {}).get("status") or "").strip().lower()
        if not name or not status:
            self.current_label.setText("ارجاع فعلی: —")
            self.current_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
            self.current_label.setToolTip("")
            return

        label = str(rec.get("status_label") or "")
        color = str(rec.get("status_color") or "#ef4444")
        suffix = f" ({label})" if label else ""
        who = name + ("  (شما)" if rec.get("mine") else "")
        self.current_label.setText(f"ارجاع فعلی: {who}{suffix}")
        self.current_label.setStyleSheet(
            f"color:{color}; font-size:11px; font-weight:600;")
        # Same detail block the Assign column's tooltip shows: by whom, when, comment.
        try:
            from modules.network import ino_assignment_details as _d
            self.current_label.setToolTip(_d.format_tooltip(rec))
        except Exception:
            pass

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
