# -*- coding: utf-8 -*-
"""INO reception report-WORKFLOW helpers — approval-flag sync.

Why this exists
---------------
INO Reception renders a report's patient status from ``report.approvalFlags``
(physicianApproved / secretaryApproved). The ``/api/pacs/update-report``
endpoint does **not** set those flags — it only writes ``report.status`` (and
the server clears the flags when the status becomes an *awaiting* one). The
approve / un-approve action is a **separate** workflow endpoint keyed by the
reception's **imagingWorkflow ObjectId**:

    PATCH {base}/api/imagingWorkflow/{workflowId}/workflow/report/approval-flags
        { "physicianApproved": bool, "secretaryApproved": bool }

The workstation only knows the **numeric** receptionId, so the ObjectId is
resolved from the reporting worklist (each item carries both the numeric
``receptionID`` and the ObjectId ``receptionId``):

    GET {base}/api/imagingWorkflow/workflow/reporting?receptionID={n}
        -> data[0].receptionId   (the imagingWorkflow ObjectId)

Both facts were live-verified 2026-07-09 on reception 49476 (workflow id
``6a4de81218a091772b582325``) — see
``docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md``.

Guarantees
----------
* Reuses the logged-in JWT (``SocketTokenManager``); stores nothing.
* Best-effort and side-effect-safe: any failure returns False and is logged —
  it never raises into the report-save path. Prefer the ``*_async`` wrapper so
  the two REST calls never run on the GUI thread.
* Reuses the Reception/API circuit breaker.
* Flag-gated: ``AIPACS_INO_APPROVAL_SYNC`` (default ON; ``=0`` disables).
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover - requests is a hard dependency of the app
    requests = None  # type: ignore

from modules.network.reception_api_config import (
    get_reception_api_base_url,
    get_reception_api_timeout,
    reception_api_breaker_open,
    record_reception_api_failure,
    record_reception_api_success,
)
from modules.network.socket_token_manager import get_socket_token_manager
from modules.network.socket_report_status_service import approval_flags_for_status

logger = logging.getLogger(__name__)

INO_APPROVAL_SYNC = (os.environ.get("AIPACS_INO_APPROVAL_SYNC", "1") or "1").strip() != "0"

_REPORTING_WORKLIST_PATH = "/api/imagingWorkflow/workflow/reporting"
_APPROVAL_FLAGS_PATH = "/api/imagingWorkflow/{wid}/workflow/report/approval-flags"
_OBJECT_ID_RE = re.compile(r"^[a-fA-F0-9]{24}$")

# Phrases INO returns when the logged-in user's ROLE lacks permission for an
# action (physician/secretary approval etc.). INO enforces access control by
# role server-side; AI-PACS must NOT bypass it — it surfaces the rejection.
_PERMISSION_PHRASES = ("مجاز نیست", "دسترسی", "مجوز", "permission", "forbidden", "not allowed", "unauthorized")


def _looks_object_id(value) -> bool:
    return bool(value) and bool(_OBJECT_ID_RE.match(str(value)))


def _classify_error(status_code: int, message: str) -> str:
    """Classify an INO error response: 'permission' | 'auth' | 'http' | ''."""
    msg = (message or "").lower()
    if status_code == 403 or any(p in (message or "") or p in msg for p in _PERMISSION_PHRASES):
        return "permission"
    if status_code == 401:
        return "auth"
    if status_code and status_code >= 400:
        return "http"
    return ""


# --- UI notifier (GUI-thread-safe) -------------------------------------------
# The approval sync runs fire-and-forget on a daemon thread, so it cannot pop a
# dialog directly. It emits a Qt signal instead; a GUI-thread listener (installed
# once via install_ui_notifier) shows the message. Qt delivers the cross-thread
# signal queued onto the receiver's thread, so this is safe.
try:
    from PySide6.QtCore import QObject, Signal

    class _INOApprovalNotifier(QObject):
        # (message, kind)  kind in {'permission','auth','network','http'}
        sync_failed = Signal(str, str)

    _NOTIFIER: "Optional[_INOApprovalNotifier]" = _INOApprovalNotifier()
except Exception:  # pragma: no cover - Qt always present in the app
    _NOTIFIER = None


def get_notifier():
    """Return the module notifier QObject (or None). Connect ``sync_failed`` on
    the GUI thread to surface INO permission/auth errors to the user."""
    return _NOTIFIER


def _emit_failure(message: str, kind: str) -> None:
    n = _NOTIFIER
    if n is None or not message:
        return
    try:
        n.sync_failed.emit(str(message), str(kind))
    except Exception:  # pragma: no cover - defensive
        pass


def _headers() -> Optional[dict]:
    try:
        tok = get_socket_token_manager().get_token()
    except Exception:
        tok = None
    if not tok:
        return None
    return {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def resolve_workflow_id(reception_id, base_url: Optional[str] = None, timeout: Optional[int] = None) -> Optional[str]:
    """Resolve the imagingWorkflow ObjectId for a NUMERIC ``reception_id``.

    Returns the ObjectId string, or None if it cannot be resolved. Never raises.
    """
    if requests is None:
        return None
    headers = _headers()
    if not headers:
        return None
    base = (base_url or get_reception_api_base_url()).rstrip("/")
    try:
        resp = requests.get(
            f"{base}{_REPORTING_WORKLIST_PATH}",
            params={"receptionID": reception_id},
            headers=headers,
            timeout=timeout or get_reception_api_timeout(),
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
    except Exception as exc:  # pragma: no cover - network/parse defensive
        logger.warning("[ino-approval] resolve workflow id failed for %s: %s", reception_id, exc)
        return None

    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, dict):
        items = data.get("items") or data.get("results") or data.get("list") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    # Prefer the item whose numeric receptionID matches exactly.
    for it in items:
        try:
            if str(it.get("receptionID")) == str(reception_id):
                wid = it.get("receptionId")
                if _looks_object_id(wid):
                    return str(wid)
        except Exception:
            continue
    # Fallback: a single-result worklist whose ObjectId is unambiguous.
    if len(items) == 1:
        wid = items[0].get("receptionId")
        if _looks_object_id(wid):
            return str(wid)
    return None


def set_report_approval_flags(
    workflow_id: str,
    physician_approved: bool,
    secretary_approved: bool,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> bool:
    """PATCH the report approval flags for an imagingWorkflow ObjectId. Never raises."""
    if requests is None or not _looks_object_id(workflow_id):
        return False
    headers = _headers()
    if not headers:
        return False
    base = (base_url or get_reception_api_base_url()).rstrip("/")
    url = base + _APPROVAL_FLAGS_PATH.format(wid=workflow_id)
    try:
        resp = requests.patch(
            url,
            json={
                "physicianApproved": bool(physician_approved),
                "secretaryApproved": bool(secretary_approved),
            },
            headers=headers,
            timeout=timeout or get_reception_api_timeout(),
        )
        message = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                message = str(body.get("message") or "")
        except Exception:
            message = (resp.text or "")[:200]
        ok = resp.status_code == 200
        if ok:
            record_reception_api_success(base)
        else:
            record_reception_api_failure(base)
            kind = _classify_error(resp.status_code, message)
            if kind in ("permission", "auth"):
                # INO's ROLE/access control rejected the action — surface it, do
                # NOT bypass. Logged clearly and forwarded to the UI notifier.
                logger.warning(
                    "[ino-approval] %s DENIED by INO for %s (HTTP %s): %s",
                    "PERMISSION" if kind == "permission" else "AUTH",
                    workflow_id, resp.status_code, message or "(no message)",
                )
                _emit_failure(
                    message or (
                        "شما مجاز به انجام این عملیات (تأیید گزارش) نیستید."
                        if kind == "permission"
                        else "نشست کاربری منقضی شده است. دوباره وارد شوید."
                    ),
                    kind,
                )
            else:
                logger.warning(
                    "[ino-approval] PATCH approval-flags HTTP %s for %s: %s",
                    resp.status_code, workflow_id, message or "(no message)",
                )
        return ok
    except Exception as exc:  # pragma: no cover - network defensive
        record_reception_api_failure(base)
        logger.warning("[ino-approval] PATCH approval-flags failed for %s: %s", workflow_id, exc)
        return False


def sync_report_approval_for_status(reception_id, status: str, base_url: Optional[str] = None) -> bool:
    """Resolve the workflow id for a numeric reception and PATCH approvalFlags to
    match ``status`` (via :func:`approval_flags_for_status`).

    This is the *effective* status→INO sync: ``update-report`` alone cannot set
    the flags INO displays. Best-effort — returns True only on a successful
    PATCH. Never raises.
    """
    if not INO_APPROVAL_SYNC:
        return False
    if reception_api_breaker_open(base_url):
        return False
    try:
        workflow_id = resolve_workflow_id(reception_id, base_url)
        if not workflow_id:
            logger.info("[ino-approval] no workflow id for reception %s; approval flags not synced", reception_id)
            return False
        flags = approval_flags_for_status(status)
        ok = set_report_approval_flags(
            workflow_id, flags["physicianApproved"], flags["secretaryApproved"], base_url
        )
        logger.info(
            "[ino-approval] reception=%s status=%s -> physicianApproved=%s secretaryApproved=%s ok=%s",
            reception_id, status, flags["physicianApproved"], flags["secretaryApproved"], ok,
        )
        return ok
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[ino-approval] sync failed for reception %s: %s", reception_id, exc)
        return False


def sync_report_approval_for_status_async(reception_id, status: str, base_url: Optional[str] = None) -> None:
    """Fire-and-forget wrapper — runs the resolve+PATCH on a daemon thread so the
    two REST calls never block the GUI/report-save path."""
    if not INO_APPROVAL_SYNC:
        return

    def _run() -> None:
        try:
            sync_report_approval_for_status(reception_id, status, base_url)
        except Exception:  # pragma: no cover - defensive
            logger.exception("[ino-approval] async sync crashed")

    try:
        threading.Thread(target=_run, name="INOApprovalSync", daemon=True).start()
    except Exception:  # pragma: no cover - defensive
        logger.exception("[ino-approval] could not start async sync thread")


_UI_NOTIFIER_INSTALLED = False


def install_ui_notifier() -> None:
    """Idempotently connect the failure notifier to a user-facing message.

    MUST be called from the GUI thread (e.g. when the report-status UI is built)
    so the queued cross-thread signal is delivered on the GUI thread. On an INO
    permission/auth rejection the user sees a clear dialog — AI-PACS surfaces
    INO's access-control decision instead of silently succeeding.
    """
    global _UI_NOTIFIER_INSTALLED
    if _UI_NOTIFIER_INSTALLED or _NOTIFIER is None:
        return

    def _show(message: str, kind: str) -> None:
        try:
            title = "دسترسی غیرمجاز" if kind == "permission" else "خطای همگام‌سازی وضعیت"
            try:
                from PacsClient.pacs.patient_tab.utils.utils import show_message
                show_message(message, title=title)
            except Exception:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(None, title, message)
        except Exception:  # pragma: no cover - never break on a notification
            logger.warning("[ino-approval] could not display permission message: %s", message)

    try:
        _NOTIFIER.sync_failed.connect(_show)
        _UI_NOTIFIER_INSTALLED = True
    except Exception:  # pragma: no cover - defensive
        logger.exception("[ino-approval] failed to install UI notifier")
