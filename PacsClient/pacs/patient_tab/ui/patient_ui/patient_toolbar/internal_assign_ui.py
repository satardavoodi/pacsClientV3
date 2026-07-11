# -*- coding: utf-8 -*-
"""Internal-center Assign row for the existing Report Status popup.

A compact, self-contained widget added to the SAME upper section of the Report
Status popup that already holds Survey / Comment / Status. It is the ONLY UI for
the internal (same-center) assignment workflow and is completely separate from
the external Consultation flow — it drives `InternalAssignmentService` and
nothing else (no Drive, no website, no payment, no cross-center).

Behaviour:
* Shows the CURRENT assignment loaded live from INO ("ارجاع فعلی: …").
* An eligible-users dropdown populated from INO's assign-users endpoint
  (respects center/roles/permissions server-side).
* An "ارجاع" (Assign) button → submits via INO → on success updates the label
  (red = assigned/pending), records a local notification, and calls back so the
  patient row can refresh.

All network runs off the GUI thread; results marshal back via Qt signals. Safe:
if the feature is disabled or anything fails, it degrades quietly.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("ino_assignment")


class InternalAssignRow(QWidget):
    """Compact Assign control for one reception. RTL, Persian labels."""

    _loaded = Signal(object)     # {"users": [...], "assignment": {...}} or {"error": ...}
    _assigned = Signal(object)   # structured assign result

    def __init__(
        self,
        reception_id,
        assign_type: str = "radiologist",
        on_assigned: Optional[Callable[[str, str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._reception_id = str(reception_id)
        self._assign_type = assign_type
        self._on_assigned = on_assigned
        self._users: List[Any] = []
        self.setLayoutDirection(Qt.RightToLeft)

        self._build()
        self._loaded.connect(self._on_loaded)
        self._assigned.connect(self._on_assign_result)
        self._start_load()

    # -- UI ---------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(3)

        header = QLabel("ارجاع داخلی مرکز")
        header.setStyleSheet("color:#cfe0f5; font-weight:600;")
        root.addWidget(header)

        self.current_label = QLabel("در حال بارگذاری ارجاع فعلی…")
        self.current_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
        root.addWidget(self.current_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(150)
        self.user_combo.addItem("انتخاب کاربر…", "")
        self.assign_btn = QPushButton("ارجاع")
        self.assign_btn.setEnabled(False)
        self.assign_btn.clicked.connect(self._on_assign_clicked)
        row.addWidget(self.user_combo, 1)
        row.addWidget(self.assign_btn)
        root.addLayout(row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#e15759; font-size:11px;")
        root.addWidget(self.status_label)

    # -- load (off thread) ------------------------------------------------
    def _start_load(self) -> None:
        def _run():
            out: Dict[str, Any] = {}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                svc = get_internal_assignment_service()
                users = svc.list_users(self._assign_type)
                assignment = svc.current_assignment(self._reception_id)
                out["users"] = users
                out["assignment"] = assignment
            except Exception as exc:  # pragma: no cover
                out["error"] = str(exc)
            try:
                self._loaded.emit(out)
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOAssignLoad", daemon=True).start()

    def _on_loaded(self, out: Dict[str, Any]) -> None:
        users_res = (out or {}).get("users") or {}
        if users_res.get("disabled"):
            self.current_label.setText("ارجاع داخلی غیرفعال است.")
            return
        users = users_res.get("users") or []
        self._users = users
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        self.user_combo.addItem("انتخاب کاربر…", "")
        for u in users:
            name = getattr(u, "full_name", "") or getattr(u, "username", "") or getattr(u, "id", "")
            self.user_combo.addItem(name, getattr(u, "id", ""))
        self.user_combo.blockSignals(False)
        self.assign_btn.setEnabled(bool(users))

        assignment = (out or {}).get("assignment") or {}
        self._render_current(assignment.get("assignment") if assignment.get("ok") else {})

    def _render_current(self, assignment: Dict[str, Any]) -> None:
        try:
            rad = (assignment or {}).get(self._assign_type) or {}
            name = str(rad.get("name") or "").strip()
            if name:
                self.current_label.setText(f"ارجاع فعلی: {name}")
                self.current_label.setStyleSheet("color:#ef4444; font-size:11px; font-weight:600;")
            else:
                self.current_label.setText("ارجاع فعلی: —")
                self.current_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
        except Exception:
            self.current_label.setText("ارجاع فعلی: —")

    # -- assign (off thread) ----------------------------------------------
    def _selected_user(self):
        uid = self.user_combo.currentData()
        if not uid:
            return None
        for u in self._users:
            if getattr(u, "id", "") == uid:
                return u
        return None

    def _on_assign_clicked(self) -> None:
        user = self._selected_user()
        if user is None:
            self.status_label.setText("لطفاً یک کاربر انتخاب کنید.")
            return
        self.assign_btn.setEnabled(False)
        self.status_label.setStyleSheet("color:#9cb6d6; font-size:11px;")
        self.status_label.setText("در حال ارجاع…")
        name = getattr(user, "full_name", "") or getattr(user, "username", "")
        source = getattr(user, "source", "")
        try:
            from modules.network.ino_assignment import assign_async
            assign_async(
                self._reception_id, self._assign_type, getattr(user, "id", ""),
                assignee_name=name, assignee_source=source,
                on_result=lambda r: self._safe_emit_assigned(dict(r, _name=name)),
            )
        except Exception as exc:
            self._safe_emit_assigned({"ok": False, "message": str(exc), "_name": name})

    def _safe_emit_assigned(self, result: Dict[str, Any]) -> None:
        try:
            self._assigned.emit(result)
        except RuntimeError:
            pass

    def _on_assign_result(self, result: Dict[str, Any]) -> None:
        self.assign_btn.setEnabled(True)
        name = str(result.get("_name") or "")
        if result.get("ok"):
            self.status_label.setStyleSheet("color:#10b981; font-size:11px;")
            self.status_label.setText("ارجاع با موفقیت انجام شد.")
            self.current_label.setText(f"ارجاع فعلی: {name}")
            self.current_label.setStyleSheet("color:#ef4444; font-size:11px; font-weight:600;")
            # Local notification mirror (out-going assignment).
            try:
                from modules.network import ino_notifications
                ino_notifications.notify_local_assignment(self._reception_id, assignee_name=name)
            except Exception:
                pass
            if self._on_assigned:
                try:
                    self._on_assigned(name, self._reception_id)
                except Exception:
                    logger.exception("[ino-assignment] on_assigned callback failed")
        else:
            self.status_label.setStyleSheet("color:#e15759; font-size:11px;")
            if result.get("permission_denied"):
                self.status_label.setText("شما مجاز به ارجاع این پرونده نیستید.")
            elif result.get("auth_error"):
                self.status_label.setText("نشست کاربری منقضی شده است. دوباره وارد شوید.")
            elif result.get("disabled"):
                self.status_label.setText("ارجاع داخلی غیرفعال است.")
            else:
                self.status_label.setText(str(result.get("message") or "ارجاع ناموفق بود."))


def build_internal_assign_row(reception_id, on_assigned=None, parent=None) -> Optional[QWidget]:
    """Factory used by the Report Status popup. Returns the widget, or None when
    the feature is disabled / reception id is missing (so the popup is unchanged
    when internal assignment is off)."""
    try:
        from modules.network.ino_assignment import is_enabled
        if not is_enabled() or not reception_id:
            return None
        return InternalAssignRow(reception_id, on_assigned=on_assigned, parent=parent)
    except Exception:
        logger.warning("[ino-assignment] could not build assign row", exc_info=True)
        return None
