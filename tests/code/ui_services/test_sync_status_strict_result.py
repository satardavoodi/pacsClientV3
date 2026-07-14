"""FIX-2 guards — a Patient-Tab "Sync Status" that did NOT reach the server must
never be reported as a success.

Field evidence (2026-07-13):

    13:26:52  ERROR  Update failed - no response from server      <- UpdateReportStatus got EOF
    13:26:54  WARN   [VOICE-DELETE-GUARD] ... non-user teardown   <- the patient tab CLOSED anyway

``_sync_worker`` recorded the failure in ``result['errors']`` but still emitted
``sync_completed`` (``sync_failed`` fired only on an exception). The toolbar's
``on_sync_completed`` never inspected the result, so it set the study to
``physician_approved``, painted the home row green and closed the tab — while the
server had received nothing. The queued ``statusError`` message box then appeared
AFTER the tab was gone (the visible symptom the user reported).

The dangerous half is the silent state divergence, not the popup.

These tests are pure — no Qt, no network.
"""
import ast
import pathlib

import pytest

from PacsClient.pacs.patient_tab.utils.patient_sync_service import (
    _sync_failure_message,
    _sync_result_failed,
    _sync_strict_result_enabled,
)

_REPO = pathlib.Path(__file__).resolve().parents[3]
_SYNC_SRC = _REPO / "PacsClient" / "pacs" / "patient_tab" / "utils" / "patient_sync_service.py"
_TOOLBAR_SRC = (
    _REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _ok_result(**over):
    base = {
        "study_uid": "1.2.3",
        "attachments_uploaded": 2,
        "attachments_failed": 0,
        "status_updated": True,
        "errors": [],
    }
    base.update(over)
    return base


# ── the pure predicate ──────────────────────────────────────────────────────

def test_fully_successful_sync_is_not_a_failure():
    assert _sync_result_failed(_ok_result()) is False


def test_study_with_no_attachments_is_still_a_success():
    assert _sync_result_failed(
        _ok_result(attachments_uploaded=0, attachments_failed=0)
    ) is False


def test_failed_report_status_update_is_a_FAILURE():
    """THE field bug: uploads fine, server never accepted the status."""
    assert _sync_result_failed(
        _ok_result(status_updated=False, errors=["Failed to update report status"])
    ) is True


def test_failed_status_with_no_error_string_is_still_a_failure():
    assert _sync_result_failed(_ok_result(status_updated=False, errors=[])) is True


def test_failed_attachment_upload_is_a_failure():
    assert _sync_result_failed(_ok_result(attachments_failed=1)) is True


def test_any_recorded_error_is_a_failure():
    assert _sync_result_failed(_ok_result(errors=["Error uploading attachments: boom"])) is True


def test_garbage_result_is_treated_as_failure():
    assert _sync_result_failed(None) is True
    assert _sync_result_failed("nope") is True
    assert _sync_result_failed(_ok_result(attachments_failed="x")) is True


def test_failure_message_reassures_that_files_are_kept():
    msg = _sync_failure_message(
        _ok_result(status_updated=False, errors=["Failed to update report status"])
    )
    assert "Failed to update report status" in msg
    assert "locally" in msg.lower(), "the user must be told their data is safe"


def test_kill_switch(monkeypatch):
    monkeypatch.delenv("AIPACS_SYNC_STRICT_RESULT", raising=False)
    assert _sync_strict_result_enabled() is True
    monkeypatch.setenv("AIPACS_SYNC_STRICT_RESULT", "0")
    assert _sync_strict_result_enabled() is False


# ── wiring pins (source-level; no Qt needed) ────────────────────────────────

def test_worker_routes_an_unconfirmed_sync_to_sync_failed():
    src = _SYNC_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    worker = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_sync_worker"
    )
    body = ast.get_source_segment(src, worker) or ""
    assert "_sync_result_failed(result)" in body, (
        "_sync_worker must consult the strict predicate before declaring success"
    )
    assert "self.sync_failed.emit(study_uid, message)" in body
    # and the success emit must still exist for the genuinely-successful path
    assert "self.sync_completed.emit(study_uid, result)" in body


def test_toolbar_does_not_close_the_tab_on_an_unconfirmed_result():
    src = _TOOLBAR_SRC.read_text(encoding="utf-8")
    start = src.index("def on_sync_completed(")
    end = src.index("def on_sync_failed(", start)
    handler = src[start:end]
    assert "_sync_result_failed" in handler, (
        "on_sync_completed must re-validate the result — it is the site that "
        "closes the tab and writes physician_approved"
    )
    # the bail must come BEFORE the approve / close side effects
    bail = handler.index("_unconfirmed")
    approve = handler.index("report_status = _synced_status")
    close = handler.index("close_and_remove_patient_tab")
    assert bail < approve < close


def test_status_error_popup_is_suppressed_while_a_sync_owns_it():
    table = (
        _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "patient_table_widget.py"
    ).read_text(encoding="utf-8")
    start = table.index("def _on_report_status_error(")
    end = table.index("def _on_header_section_resized(", start)
    handler = table[start:end]
    assert "sync_in_progress" in handler, (
        "the orphan popup after the tab closed must be suppressed while the "
        "patient sync owns that error"
    )
    assert "AIPACS_MODAL_STATUS_ERROR" in handler, (
        "the blocking modal must sit behind a kill switch (default OFF)"
    )
    assert "box.show()" in handler, (
        "the default path must be non-modal show() — exec() spins a nested Qt "
        "event loop on the GUI thread (the 'freeze', and the re-entrancy the "
        "table-clear crash lives in)"
    )
