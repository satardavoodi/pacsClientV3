# -*- coding: utf-8 -*-
"""Internal-assignment notifications — local store + profile-icon badge.

A small, isolated notification system for the **internal-center assignment**
feature: when a case is assigned to the logged-in user, a notification is stored
and the profile/user icon shows a red unread indicator. Separate from the
external consultation notifications.

Pieces:
* `NotificationStore` — per-user JSONL of notifications (read/unread), local.
* `NotificationCenter` (QObject singleton) — signals `unread_changed(int)` and
  `notification_added(dict)` the UI connects to (thread-safe queued delivery).
* `attach_profile_badge(icon_widget)` — paints a red dot on the profile icon and
  keeps it in sync with the unread count.
* `on_study_assigned(event)` — entry point for the socket `study_assigned`
  handler (wired later) to record an incoming assignment for THIS user.

Imports only stdlib + Qt + the assignment models — never the consultation code.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ino_assignment")

_LOCK = threading.Lock()
_SUBDIR = "ino_assignment"
_FILENAME = "notifications.jsonl"


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def _base_dir() -> str:
    try:
        from PacsClient.utils import data_paths as _dp

        root = getattr(_dp, "CLINICAL_DATA_ROOT", None) or getattr(_dp, "USER_DATA_ROOT", None)
        if root:
            return os.path.join(str(root), _SUBDIR)
    except Exception:
        pass
    if os.name == "nt":
        base = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".aipacs")
    return os.path.join(base, "user_data", _SUBDIR)


def _path() -> str:
    d = _base_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, _FILENAME)


def _read_all() -> List[Dict[str, Any]]:
    p = _path()
    rows: List[Dict[str, Any]] = []
    try:
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
    except Exception:
        return []
    return rows


def _write_all(rows: List[Dict[str, Any]]) -> None:
    p = _path()
    try:
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover
        logger.warning("[ino-assignment] could not write notifications: %s", exc)


def add_notification(
    reception_id,
    title: str,
    body: str,
    *,
    assigner: str = "",
    status: str = "",
    kind: str = "assignment",
    patient_name: str = "",
) -> Dict[str, Any]:
    """Append an unread notification. Returns the created record."""
    rec = {
        "id": f"{reception_id}-{int(_dt.datetime.now().timestamp() * 1000)}",
        "reception_id": str(reception_id),
        "title": title,
        "body": body,
        "assigner": assigner,
        "status": status,
        "kind": kind,
        "patient_name": patient_name,
        "read": False,
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    with _LOCK:
        rows = _read_all()
        rows.append(rec)
        _write_all(rows[-500:])  # cap
    logger.info("[ino-assignment] notification added reception=%s: %s", reception_id, title)
    _center_emit()
    return rec


def list_notifications(limit: int = 100) -> List[Dict[str, Any]]:
    rows = _read_all()
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[:limit] if limit else rows


def unread_count() -> int:
    return sum(1 for r in _read_all() if not r.get("read"))


def mark_all_read() -> None:
    with _LOCK:
        rows = _read_all()
        changed = False
        for r in rows:
            if not r.get("read"):
                r["read"] = True
                changed = True
        if changed:
            _write_all(rows)
    _center_emit()


def mark_read(notification_id: str) -> None:
    with _LOCK:
        rows = _read_all()
        for r in rows:
            if r.get("id") == notification_id:
                r["read"] = True
        _write_all(rows)
    _center_emit()


# --------------------------------------------------------------------------- #
# Qt notification center (singleton)
# --------------------------------------------------------------------------- #
try:
    from PySide6.QtCore import QObject, Signal

    class _NotificationCenter(QObject):
        unread_changed = Signal(int)          # new unread count
        notification_added = Signal(object)   # the record dict

    _CENTER: "Optional[_NotificationCenter]" = _NotificationCenter()
except Exception:  # pragma: no cover
    _CENTER = None


def get_center():
    return _CENTER


def _center_emit() -> None:
    c = _CENTER
    if c is None:
        return
    try:
        c.unread_changed.emit(unread_count())
    except Exception:  # pragma: no cover
        pass


# --------------------------------------------------------------------------- #
# Socket entry point (wired later) + local-assign convenience
# --------------------------------------------------------------------------- #
def notify_local_assignment(reception_id, assignee_name: str = "", assigner: str = "") -> None:
    """Convenience used right after a successful local assign, to mirror the
    assignment as a notification (e.g. when assigning to oneself). The true
    cross-machine delivery for OTHER users comes from ``on_study_assigned``."""
    add_notification(
        reception_id,
        title=f"پرونده {reception_id} ارجاع داده شد",
        body=f"پرونده {reception_id}" + (f" به {assignee_name}" if assignee_name else "") + " ارجاع داده شد.",
        assigner=assigner,
        kind="assignment_out",
    )


def notify_assignment(reception_id, assignee_name: str = "", patient_name: str = "",
                      assigner: str = "") -> Dict[str, Any]:
    """Create an INTERNAL-assignment notification identifying the patient.

    Used right after the INO server confirms an internal assignment (the Assign
    column / Report popup). ``kind="assignment_in"`` marks it as an internal
    assignment so the click handler routes to the patient list (never the
    consultation / Drive flow). Carries the ``reception_id`` for navigation."""
    who = (patient_name or "").strip() or f"پرونده {reception_id}"
    to = (assignee_name or "").strip()
    return add_notification(
        reception_id,
        title=f"ارجاع داخلی مرکز — {reception_id}",
        body=f"{who} به {to or 'شما'} ارجاع داده شد.",
        assigner=assigner,
        patient_name=patient_name,
        kind="assignment_in",
    )


# --------------------------------------------------------------------------- #
# Click → navigate (patient list). The workstation registers a callback that
# searches/selects a reception in the patient table. INTERNAL only — this never
# opens the consultation / Drive workflow.
# --------------------------------------------------------------------------- #
_NAV_CB = None


def set_navigate_callback(cb) -> None:
    """Register ``cb(reception_id: str)`` — invoked when a notification is clicked."""
    global _NAV_CB
    _NAV_CB = cb


def navigate_to(reception_id) -> bool:
    """Invoke the registered navigate callback for a reception id. Returns True
    when a callback handled it."""
    cb = _NAV_CB
    if cb is None:
        logger.info("[ino-assignment] notification click: no navigate callback registered (reception=%s)", reception_id)
        return False
    try:
        cb(str(reception_id))
        return True
    except Exception:  # pragma: no cover - never break the UI
        logger.exception("[ino-assignment] navigate callback failed")
        return False


def on_study_assigned(event: Dict[str, Any]) -> None:
    """Entry point for the INO socket ``study_assigned`` broadcast handler.

    Call this from the socket layer when a targeted ``study_assigned`` event for
    THIS logged-in user arrives. Records an unread notification + bumps the badge.
    (The socket subscription/handler wiring is a separate, later step.)
    """
    try:
        data = event.get("data") if isinstance(event, dict) else {}
        data = data or {}
        rid = data.get("patient_id") or data.get("reception_id") or ""
        assigner = str(data.get("assigned_by") or "")
        add_notification(
            rid,
            title=f"پرونده {rid} به شما ارجاع شد",
            body=f"پرونده {rid} به شما ارجاع داده شد." + (f" (ارجاع‌دهنده: {assigner})" if assigner else ""),
            assigner=assigner,
            status=str(data.get("assign_type") or ""),
            kind="assignment_in",
        )
    except Exception:  # pragma: no cover - never break the socket loop
        logger.exception("[ino-assignment] on_study_assigned failed")


# --------------------------------------------------------------------------- #
# Profile-icon badge
# --------------------------------------------------------------------------- #
def attach_profile_badge(icon_widget) -> Optional[object]:
    """Overlay a red unread-dot on the profile/user icon and keep it in sync.

    ``icon_widget`` is any QWidget (the existing user/person icon/button). Safe:
    returns None (no-op) if Qt is unavailable or anything fails. Idempotent per
    widget (guarded by a marker attribute).
    """
    if _CENTER is None or icon_widget is None:
        return None
    try:
        if getattr(icon_widget, "_ino_badge_attached", False):
            return getattr(icon_widget, "_ino_badge", None)
        from PySide6.QtCore import QRect, Qt
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QWidget

        class _Badge(QWidget):
            def __init__(self, host):
                super().__init__(host)
                self._count = 0
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self.setFixedSize(12, 12)
                self.hide()

            def set_count(self, n: int):
                self._count = int(n or 0)
                self.setVisible(self._count > 0)
                self._reposition()
                self.update()

            def _reposition(self):
                p = self.parentWidget()
                if p is not None:
                    self.move(max(0, p.width() - self.width()), 0)

            def paintEvent(self, _e):
                qp = QPainter(self)
                qp.setRenderHint(QPainter.Antialiasing)
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor("#ef4444"))
                qp.drawEllipse(QRect(1, 1, 10, 10))

        badge = _Badge(icon_widget)
        badge.set_count(unread_count())
        try:
            _CENTER.unread_changed.connect(badge.set_count)
        except Exception:
            pass
        # Clicking the profile/user icon opens the notifications popup. Preserve
        # any existing handler by chaining to it after opening the popup.
        try:
            _prev = getattr(icon_widget, "mousePressEvent", None)

            def _open_notifs(ev, _w=icon_widget, _p=_prev):
                try:
                    open_notifications_popup(_w)
                except Exception:
                    logger.debug("open notifications popup failed", exc_info=True)
                if callable(_p):
                    try:
                        _p(ev)
                    except Exception:
                        pass

            icon_widget.setCursor(Qt.PointingHandCursor)
            icon_widget.mousePressEvent = _open_notifs
        except Exception:
            pass
        icon_widget._ino_badge = badge
        icon_widget._ino_badge_attached = True
        return badge
    except Exception:  # pragma: no cover
        logger.warning("[ino-assignment] could not attach profile badge", exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# Notifications popup (list + click → navigate). INTERNAL assignment only.
# --------------------------------------------------------------------------- #
def _notif_row_widget(rec: Dict[str, Any], dlg):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

    f = QFrame()
    f.setObjectName("inoNotifRow")
    unread = not rec.get("read")
    f.setStyleSheet(
        "QFrame#inoNotifRow{background:%s;border:1px solid rgba(148,163,184,0.18);"
        "border-radius:8px;} QFrame#inoNotifRow:hover{background:rgba(59,130,246,0.15);}"
        % ("rgba(59,130,246,0.10)" if unread else "transparent"))
    f.setCursor(Qt.PointingHandCursor)
    vl = QVBoxLayout(f)
    vl.setContentsMargins(10, 8, 10, 8)
    vl.setSpacing(2)
    t = QLabel(str(rec.get("title") or ""))
    t.setStyleSheet("font-weight:%s;font-size:12px;" % ("700" if unread else "500"))
    b = QLabel(str(rec.get("body") or ""))
    b.setWordWrap(True)
    b.setStyleSheet("color:#9ca3af;font-size:11px;")
    vl.addWidget(t)
    vl.addWidget(b)

    def _click(_e, rid=str(rec.get("reception_id") or ""), nid=str(rec.get("id") or "")):
        try:
            mark_read(nid)
        except Exception:
            pass
        # Internal assignment → route to the patient list only (never consultation).
        navigate_to(rid)
        try:
            dlg.accept()
        except Exception:
            pass

    f.mousePressEvent = _click
    return f


def open_notifications_popup(anchor=None) -> Optional[object]:
    """A small popup listing internal-assignment notifications; clicking one marks
    it read and navigates to that reception in the patient list."""
    if _CENTER is None:
        return None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
            QVBoxLayout, QWidget,
        )
    except Exception:
        return None
    try:
        parent = anchor.window() if (anchor is not None and hasattr(anchor, "window")) else None
        dlg = QDialog(parent)
        dlg.setWindowTitle("اعلان‌های ارجاع داخلی")
        dlg.setWindowFlags(Qt.Popup)          # auto-closes on outside click
        dlg.setMinimumWidth(340)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel("اعلان‌های ارجاع داخلی مرکز")
        title.setStyleSheet("font-weight:600;font-size:13px;")
        mark = QPushButton("خواندن همه")
        mark.setCursor(Qt.PointingHandCursor)
        mark.clicked.connect(lambda: (mark_all_read(), dlg.accept()))
        hdr.addWidget(title, 1)
        hdr.addWidget(mark)
        lay.addLayout(hdr)

        rows = list_notifications(50)
        if not rows:
            empty = QLabel("اعلانی وجود ندارد.")
            empty.setStyleSheet("color:#9ca3af;padding:12px;")
            lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            host = QWidget()
            vl = QVBoxLayout(host)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(4)
            for r in rows:
                vl.addWidget(_notif_row_widget(r, dlg))
            vl.addStretch(1)
            scroll.setWidget(host)
            scroll.setMinimumHeight(min(380, 64 * max(1, len(rows))))
            lay.addWidget(scroll)

        if anchor is not None:
            try:
                g = anchor.mapToGlobal(anchor.rect().bottomRight())
                dlg.adjustSize()
                dlg.move(max(0, g.x() - dlg.width()), g.y() + 4)
            except Exception:
                pass
        dlg.show()
        return dlg
    except Exception:  # pragma: no cover
        logger.warning("[ino-assignment] could not open notifications popup", exc_info=True)
        return None
