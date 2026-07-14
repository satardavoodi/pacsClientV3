# -*- coding: utf-8 -*-
"""THE internal-center (INO) assignment component — one engine, two entry points.

This is the SINGLE UI for internal assignment. Both entry points use it:

  * Patient list → **Assign** column → Consultation dialog → *Internal* tab
    (the education/consultation dialog EMBEDS :class:`InternalAssignmentPanel`).
  * Patient list → **Reporting Physician** column → Report Status popup →
    "manage internal assignment" (opens :class:`InternalAssignmentDialog`, which
    wraps the same panel).

Do NOT re-implement any of this anywhere else. There must be exactly one form,
one status model, one API path, one notification, one history.

It lives in **core** (not in the education plugin) on purpose: internal
assignment is an INO/core feature and must not depend on the purchasable
consultation module. The dependency direction is education → core, never core →
education. EXTERNAL consultation stays entirely in the education module.

Everything is driven by ``modules.network.ino_assignment`` (the one service):
eligible users, assign/reassign, lifecycle status, unassign, history,
notifications. All network runs off the GUI thread; results marshal back via Qt
signals.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("ino_assignment")

_MUTED = "#9cb6d6"
_TEXT = "#e6edf6"
_BORDER = "rgba(148,163,184,0.25)"
_SURFACE = "rgba(148,163,184,0.08)"


def internal_assignment_available(reception_id=None) -> bool:
    """True when the internal-assignment feature is on (and we have a reception)."""
    try:
        from modules.network.ino_assignment import is_enabled

        if not is_enabled():
            return False
    except Exception:
        return False
    if reception_id is not None and not str(reception_id).strip():
        return False
    return True


class InternalAssignmentPanel(QWidget):
    """The one internal-assignment form: eligible users + current assignment +
    lifecycle actions. Embed it anywhere; never copy it."""

    # (reception_id, assignee_name) — emitted after the server confirms an
    # assignment OR a lifecycle change, so the patient list can refresh.
    assigned = Signal(str, str)

    _users_loaded = Signal(object)
    _assign_done = Signal(object)
    _status_done = Signal(object)

    def __init__(self, reception_id, patient_name: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._reception_id = str(reception_id or "")
        self._patient_name = str(patient_name or "")
        self._users: List[Any] = []
        self._selected: set = set()

        self._build()
        try:
            self._users_loaded.connect(self._on_users_loaded)
            self._assign_done.connect(self._on_assign_done)
            self._status_done.connect(self._on_status_done)
        except Exception:
            pass
        self._load_details()
        self._start_load_users()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # -- current assignment card (assignee / assigner / type / when / comment)
        self._card = QFrame()
        self._card.setObjectName("iaCard")
        self._card.setStyleSheet(
            "QFrame#iaCard{background:%s;border:1px solid %s;"
            "border-left:4px solid #3b82f6;border-radius:9px;}" % (_SURFACE, _BORDER))
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(14, 10, 14, 12)
        cl.setSpacing(8)

        hdr = QHBoxLayout()
        title = QLabel("Current assignment · وضعیت ارجاع فعلی")
        title.setStyleSheet(f"color:{_TEXT};font-size:13px;font-weight:700;")
        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignCenter)
        hdr.addWidget(title)
        hdr.addStretch(1)
        hdr.addWidget(self._badge)
        cl.addLayout(hdr)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)
        self._fields: Dict[str, Any] = {}
        for r, (key, cap) in enumerate([
            ("assigned_to", "👤  Assigned to"),
            ("assigned_by", "✍️  Assigned by"),
            ("type", "🏷️  Assignment type"),
            ("assigned_at", "🕒  Assigned at"),
            ("comment", "💬  Comment"),
        ]):
            c = QLabel(cap)
            c.setStyleSheet(f"color:{_MUTED};font-size:11px;font-weight:600;")
            c.setMinimumWidth(120)
            v = QLabel("—")
            v.setWordWrap(True)
            v.setStyleSheet(f"color:{_TEXT};font-size:12px;")
            grid.addWidget(c, r, 0, Qt.AlignTop | Qt.AlignLeft)
            grid.addWidget(v, r, 1, Qt.AlignTop | Qt.AlignLeft)
            self._fields[key] = (c, v)
        cl.addLayout(grid)

        acts = QHBoxLayout()
        acts.setSpacing(8)
        # THREE states (2026-07-14). Deactivate / Cancel / Unassign all meant the
        # same thing — the assignment comes off the user and the patient — so they
        # collapse into ONE action: Remove.
        self._buttons: Dict[str, QPushButton] = {}
        for key, text in (("active", "Reactivate"),
                          ("completed", "Mark Completed"),
                          ("removed", "Remove Assignment")):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("font-size:11px;padding:5px 10px;")
            b.clicked.connect(lambda _=False, k=key: self._on_status_action(k))
            self._buttons[key] = b
            acts.addWidget(b)
        acts.addStretch(1)
        cl.addLayout(acts)

        self._hint = QLabel(
            "Remove Assignment (deactivate / cancel / unassign are the same thing) is "
            "sent to the server and applied only after confirmation. Reactivate and "
            "Mark Completed are LOCAL workflow states — the server's assign model has "
            "no status field, so it cannot store them.")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color:{_MUTED};font-size:10px;")
        cl.addWidget(self._hint)

        self._card.setVisible(False)
        root.addWidget(self._card)

        # -- eligible users (grouped: Physicians / Users-Secretaries)
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Search center users — physicians & secretaries (name, role)…")
        self._search.textChanged.connect(lambda _t: self._render_users())
        root.addWidget(self._search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(260)
        host = QWidget()
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(4, 4, 4, 4)
        self._list.setSpacing(6)
        self._list.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        note_lbl = QLabel("Note / comment (saved with the assignment)")
        note_lbl.setStyleSheet(f"color:{_MUTED};font-size:11px;font-weight:500;")
        root.addWidget(note_lbl)
        self._note = QPlainTextEdit()
        self._note.setFixedHeight(56)
        self._note.setPlaceholderText("Clinical question / context…")
        root.addWidget(self._note)

        bottom = QHBoxLayout()
        self._state = QLabel("Loading center users…")
        self._state.setWordWrap(True)
        self._state.setStyleSheet(f"color:{_MUTED};font-size:12px;")
        bottom.addWidget(self._state, 1)
        self._send = QPushButton("Assign to selected (0)")
        self._send.setObjectName("primary")
        self._send.setEnabled(False)
        self._send.clicked.connect(self._on_assign_clicked)
        bottom.addWidget(self._send)
        root.addLayout(bottom)

    def _set_state(self, text: str, kind: str = "info"):
        color = {"error": "#ef4444", "success": "#10b981"}.get(kind, _MUTED)
        weight = "600" if kind in ("error", "success") else "400"
        try:
            self._state.setStyleSheet(
                f"color:{color};font-size:12px;font-weight:{weight};")
            self._state.setText(text)
        except Exception:
            pass

    # ── eligible users ────────────────────────────────────────────────────
    def _start_load_users(self):
        rid = self._reception_id

        def _run():
            out: Dict[str, Any] = {"ok": False, "users": []}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                res = get_internal_assignment_service().list_users("all")
                out = res if isinstance(res, dict) else out
            except Exception as exc:  # pragma: no cover - defensive
                out = {"ok": False, "message": str(exc), "users": []}
            try:
                self._users_loaded.emit(out)
            except RuntimeError:
                pass

        logger.info("[ino-assignment] loading eligible users (reception=%s)", rid)
        threading.Thread(target=_run, name="INOPanelUsers", daemon=True).start()

    def _on_users_loaded(self, res: object):
        data = res if isinstance(res, dict) else {}
        if data.get("disabled"):
            self._set_state("Internal assignment is disabled.", "error")
            return
        self._users = list(data.get("users") or [])
        if not self._users and data.get("ok") is False and data.get("message"):
            self._set_state(
                f"Could not load center users from INO — {data.get('message')}", "error")
        else:
            self._set_state(f"{len(self._users)} center user(s) available.")
        self._render_users()

    def _matches(self, u, q: str) -> bool:
        q = (q or "").strip().lower()
        if not q:
            return True
        hay = " ".join(str(getattr(u, k, "") or "")
                       for k in ("full_name", "username", "role")).lower()
        return q in hay

    def _clear_list(self):
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_users(self):
        self._clear_list()
        rows = [u for u in self._users if self._matches(u, self._search.text())]
        if not rows:
            lbl = QLabel("No center user matches." if self._users
                         else "No center users are available yet.")
            lbl.setStyleSheet(f"color:{_MUTED};font-size:12px;padding:10px;")
            self._list.insertWidget(0, lbl)
            self._update_send()
            return
        try:
            from modules.network import ino_assignment_models as m
            groups = m.partition_user_groups(rows)
        except Exception:
            groups = [("all", "", rows)]
        for _key, title, members in groups:
            if title:
                h = QLabel(f"{title} ({len(members)})")
                h.setStyleSheet(
                    f"color:{_TEXT};font-size:12px;font-weight:600;padding:8px 2px 2px;")
                self._list.insertWidget(self._list.count() - 1, h)
            for u in members:
                self._list.insertWidget(self._list.count() - 1, self._user_card(u))
        self._update_send()

    def _user_card(self, u) -> QWidget:
        uid = str(getattr(u, "id", "") or "")
        f = QFrame()
        f.setStyleSheet(
            "QFrame{background:%s;border:1px solid %s;border-radius:9px;}" % (_SURFACE, _BORDER))
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        cb = QCheckBox()
        cb.setChecked(uid in self._selected)
        cb.toggled.connect(lambda on, i=uid: self._on_toggle(i, on))
        lay.addWidget(cb, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(3)
        name = QLabel(str(getattr(u, "full_name", "") or getattr(u, "username", "") or "—"))
        name.setStyleSheet(f"color:{_TEXT};font-size:14px;font-weight:600;")
        col.addWidget(name)
        role = str(getattr(u, "role", "") or "")
        if role:
            r = QLabel(role)
            r.setStyleSheet(f"color:{_MUTED};font-size:12px;")
            col.addWidget(r)
        lay.addLayout(col, 1)
        return f

    def _on_toggle(self, uid: str, on: bool):
        if not uid:
            return
        if on:
            self._selected.add(uid)
        else:
            self._selected.discard(uid)
        self._update_send()

    def _update_send(self):
        n = len(self._selected)
        try:
            self._send.setText(f"Assign to selected ({n})")
            self._send.setEnabled(n > 0)
        except Exception:
            pass

    # ── assign / reassign ─────────────────────────────────────────────────
    def _on_assign_clicked(self):
        targets = [u for u in self._users
                   if str(getattr(u, "id", "") or "") in self._selected]
        if not targets:
            return
        rid = self._reception_id
        comment = self._note.toPlainText().strip()
        try:
            from modules.network import ino_assignment_history as _h
            is_reassign = bool(_h.current_assignee(rid))
        except Exception:
            is_reassign = False

        self._send.setEnabled(False)
        self._set_state(f"Assigning to {len(targets)} user(s)…")

        def _run():
            ok, errors, last = 0, [], ""
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                svc = get_internal_assignment_service()
                for u in targets:
                    types = list(getattr(u, "assign_types", []) or [])
                    atype = types[0] if types else "radiologist"
                    r = svc.assign(
                        rid, atype, str(getattr(u, "id", "") or ""),
                        assignee_name=str(getattr(u, "full_name", "") or ""),
                        assignee_source=str(getattr(u, "source", "") or ""),
                        comment=comment, is_reassignment=is_reassign,
                    ) or {}
                    if r.get("ok"):
                        ok += 1
                        last = str(getattr(u, "full_name", "") or "") or last
                    else:
                        if r.get("permission_denied"):
                            msg = "not permitted"
                        elif r.get("auth_error"):
                            msg = "sign-in expired"
                        else:
                            msg = str(r.get("message") or "failed")[:120]
                        errors.append(f"{getattr(u, 'full_name', '?')}: {msg}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(str(exc)[:160])
            try:
                self._assign_done.emit({"ok": ok, "errors": errors, "name": last})
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOPanelAssign", daemon=True).start()

    def _on_assign_done(self, res: object):
        data = res if isinstance(res, dict) else {}
        ok = int(data.get("ok") or 0)
        errors = list(data.get("errors") or [])
        name = str(data.get("name") or "")
        self._update_send()
        if ok:
            # Server confirmed → one notification, one history row, one refresh.
            self._notify(name)
            self._load_details()
            try:
                self.assigned.emit(self._reception_id, name)
            except RuntimeError:
                pass
        if ok and not errors:
            self._set_state(f"Internal assignment done ({ok}).", "success")
        elif ok:
            self._set_state(
                f"Assigned {ok}; {len(errors)} failed — " + "; ".join(errors), "error")
        else:
            self._set_state("Internal assignment failed — " + "; ".join(errors), "error")

    def _notify(self, assignee_name: str):
        try:
            from modules.network import ino_notifications
            ino_notifications.notify_assignment(
                self._reception_id, assignee_name=assignee_name,
                patient_name=self._patient_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ino notification create failed: %s", exc)

    # ── current assignment + lifecycle ────────────────────────────────────
    def _load_details(self):
        """Show WHO the patient is assigned to — from the SERVER.

        2026-07-14: this used to read ``ino_assignment_history`` (the LOCAL action
        log) only, so a reception assigned on ANOTHER workstation (50210) had no
        local record and the card simply stayed hidden — the UI could say "assigned"
        but never who. It now reads the merged accessor
        (``ino_assignment_details.get_assignment_details``): the SERVER owns the
        assignee / assigner / timestamp, the local log still supplies the comment
        and the completed/deactivated lifecycle states.
        """
        rec = None
        try:
            from modules.network import ino_assignment_details as _d
            rec = _d.get_assignment_details(self._reception_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("assignment details load failed: %s", exc)
        if not rec or not str(rec.get("status") or "").strip():
            self._card.setVisible(False)
            return
        status = str(rec.get("status") or "").strip().lower()
        s_label = str(rec.get("status_label") or status.capitalize() or "—")
        s_color = str(rec.get("status_color") or "#6b7280")
        self._badge.setText(s_label)
        self._badge.setStyleSheet(
            "background:%s22;color:%s;border:1px solid %s66;border-radius:10px;"
            "padding:3px 12px;font-size:11px;font-weight:700;" % (s_color, s_color, s_color))

        def _set(key, text):
            cap, val = self._fields[key]
            has = bool(str(text or "").strip())
            val.setText(str(text) if has else "—")
            return has

        _who = str(rec.get("assignee_name") or "")
        if _who and rec.get("mine"):
            _who += "  (you)"
        _set("assigned_to", _who)
        # The server returns the assigner as a raw user id; resolve it to a name.
        _set("assigned_by", rec.get("assigned_by_name") or rec.get("assigned_by_id"))
        _role = str(rec.get("assign_type") or "")
        _set("type", f"Internal — ارجاع داخلی مرکز" + (f" ({_role})" if _role else ""))
        _set("assigned_at", rec.get("assigned_at"))
        has_c = _set("comment", rec.get("comment"))
        cap, val = self._fields["comment"]
        cap.setVisible(has_c)
        val.setVisible(has_c)

        # THREE states (2026-07-14): active / completed / removed.
        # "Deactivate", "Cancel" and "Unassign" all meant the same thing — the
        # assignment comes off the user and the patient — so they are ONE action.
        from modules.network.ino_assignment_models import ASSIGN_TRANSITIONS
        allowed = ASSIGN_TRANSITIONS.get(status, ASSIGN_TRANSITIONS[""])
        for k, b in self._buttons.items():
            b.setEnabled(k in allowed)
        self._card.setVisible(True)

    def _on_status_action(self, status_key: str):
        rid = self._reception_id
        for b in self._buttons.values():
            b.setEnabled(False)
        self._set_state(f"Updating assignment status → {status_key}…")

        def _run():
            out = {"ok": False, "message": "unknown"}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                out = get_internal_assignment_service().set_assignment_status(
                    rid, status_key) or out
            except Exception as exc:  # pragma: no cover - defensive
                out = {"ok": False, "message": str(exc)[:160]}
            try:
                self._status_done.emit(out)
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOPanelStatus", daemon=True).start()

    def _on_status_done(self, res: object):
        data = res if isinstance(res, dict) else {}
        if data.get("ok"):
            local = bool(data.get("local"))
            what = str(data.get("status_set") or "updated")
            self._set_state(
                f"Assignment status: {what}"
                + (" (local workflow state)" if local else " — confirmed by server."),
                "success")
            self._load_details()
            try:
                self.assigned.emit(self._reception_id, "")
            except RuntimeError:
                pass
        else:
            if data.get("unsupported_by_server"):
                # The server cannot clear an assignment (assignee_id minLength=1,
                # no DELETE verb). Say exactly that — and do NOT fake a removal.
                msg = str(data.get("message") or "the server refused the removal")
            elif data.get("permission_denied"):
                msg = "not permitted"
            elif data.get("disabled"):
                msg = "internal assignment is disabled"
            else:
                msg = str(data.get("message") or "failed")[:160]
            self._set_state(f"Status change failed — {msg}", "error")
            logger.warning("[ino-assignment] status change failed: %s", msg)
            self._load_details()   # restore the true state — never a fake UI


class InternalAssignmentDialog(QDialog):
    """Standalone wrapper around :class:`InternalAssignmentPanel` — the entry
    point used from the Reporting Physician column. Same panel, same engine."""

    assigned = Signal(str, str)

    def __init__(self, reception_id, patient_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("ارجاع داخلی مرکز — Internal assignment")
        self.setMinimumSize(640, 700)
        try:
            self.resize(720, 780)
        except Exception:
            pass
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        ref = f"{reception_id} {patient_name}".strip()
        title = QLabel(f"Internal assignment — {ref}")
        title.setStyleSheet(f"color:{_TEXT};font-size:15px;font-weight:600;")
        root.addWidget(title)

        self.panel = InternalAssignmentPanel(reception_id, patient_name, parent=self)
        self.panel.assigned.connect(self.assigned)
        root.addWidget(self.panel, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)


def open_internal_assignment_dialog(reception_id, patient_name: str = "",
                                    parent=None, on_assigned=None):
    """Open THE internal-assignment component. Returns the dialog, or None when
    the feature is off / no reception id (caller then does nothing)."""
    if not internal_assignment_available(reception_id):
        return None
    try:
        dlg = InternalAssignmentDialog(reception_id, patient_name, parent=parent)
        if on_assigned:
            dlg.assigned.connect(on_assigned)
        dlg.exec()
        return dlg
    except Exception:
        logger.warning("[ino-assignment] could not open internal assignment dialog",
                       exc_info=True)
        return None
