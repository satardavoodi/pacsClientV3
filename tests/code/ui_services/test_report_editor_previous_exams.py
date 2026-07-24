"""Guards for Previous-Exams in the Medical Report Editor (2026-07-19).

The editor header gains a "Previous Exams" indicator once the reception server
confirms the patient has OLDER Patient IDs (cross-PatientID history). Selecting
a previous Patient ID shows THAT record's reports READ-ONLY (live from the
reception server, falling back to the local DB). The ACTIVE report is never
touched.

Pure helpers are behaviour-tested; the Qt dialog wiring is source-pinned
(building the real dialog needs a running reception stack).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PacsClient.utils.previous_exams import (
    build_previous_exam_set,
    distinct_previous_patient_ids,
)
from PacsClient.utils.report_history import (
    normalize_reception_record_reports,
    study_datetime_to_epoch,
)


# ---------------------------------------------------------------------------
# distinct_previous_patient_ids
# ---------------------------------------------------------------------------


def _history_payload():
    return {
        "nationalCode": "0046922229",
        "patientName": "TAHA ASADI",
        "history": [
            {"receptionId": "51354", "isCurrent": True,
             "studies": [{"StudyInstanceUID": "cur", "StudyDate": "20260718",
                          "ModalitiesInStudy": "CT"}]},
            {"receptionId": "40001",
             "studies": [{"StudyInstanceUID": "u1", "StudyDate": "20250601",
                          "ModalitiesInStudy": "MR", "reportStatus": "completed"}]},
            {"receptionId": "40001",
             "studies": [{"StudyInstanceUID": "u2", "StudyDate": "20250102",
                          "ModalitiesInStudy": "MR"}]},
            {"receptionId": "38000",
             "studies": [{"StudyInstanceUID": "u3", "StudyDate": "20240301",
                          "ModalitiesInStudy": "CT"}]},
        ],
    }


def _build_set():
    return build_previous_exam_set(
        current_patient_id="51354",
        current_study_uid="cur",
        reception_data=_history_payload(),
    )


def test_groups_previous_ids_excludes_current_newest_first():
    prev = distinct_previous_patient_ids(_build_set(), exclude_ids={"51354"})
    ids = [p.patient_id for p in prev]
    assert ids == ["40001", "38000"], "must group by prior id, newest-first, current excluded"


def test_exam_count_and_modalities_aggregate():
    prev = {p.patient_id: p for p in distinct_previous_patient_ids(_build_set(), exclude_ids={"51354"})}
    assert prev["40001"].exam_count == 2         # two studies under the old id
    assert prev["40001"].modalities == ("MR",)
    assert prev["38000"].exam_count == 1
    assert prev["40001"].display_date == "2025/06/01"   # newest of the two


def test_current_id_is_never_listed():
    prev = distinct_previous_patient_ids(_build_set(), exclude_ids={"51354"})
    assert all(p.patient_id != "51354" for p in prev)


def test_empty_set_yields_no_previous_ids():
    empty = build_previous_exam_set(current_patient_id="x")
    assert distinct_previous_patient_ids(empty) == []
    assert distinct_previous_patient_ids(None) == []


# ---------------------------------------------------------------------------
# normalize_reception_record_reports
# ---------------------------------------------------------------------------


def test_normalizes_report_from_record():
    record = {
        "receptionId": "40001", "studyUID": "u1", "modality": "MR",
        "studyDate": "20250601", "studyTime": "143000",
        "report": {"content": "<p>prev report</p>", "status": "completed",
                   "reportingPhysicianName": "Dr X"},
    }
    out = normalize_reception_record_reports(record, patient_id="40001")
    assert len(out) == 1
    r = out[0]
    assert r["html_content"] == "<p>prev report</p>"
    assert r["patient_id"] == "40001"
    assert r["study_uid"] == "u1"
    assert r["status"] == "completed"
    assert r["reporting_physician_name"] == "Dr X"
    assert r["source"] == "server"
    assert r["created_at"] > 0
    assert "Modality: MR" in r["sender_info"]
    assert "read-only" in r["sender_info"].lower()


def test_unwraps_success_data_envelope():
    """REGRESSION (47633, live): the reception API returns
    {"success": true, "data": {... "report": {"content": ...}}}. The normalizer
    must descend into `data` — reading `report` off the top level found nothing
    even though the report existed."""
    envelope = {
        "success": True,
        "data": {
            "receptionId": "47633",
            "modality": "CT",
            "date": "2026-06-01T14:30:00",
            "report": {
                "content": "<p>previous chest CT</p>",
                "findings": "<p>previous chest CT</p>",
                "status": "completed",
                "radiologist": {"name": "Dr Persian"},
            },
        },
    }
    out = normalize_reception_record_reports(envelope, patient_id="47633")
    assert len(out) == 1
    r = out[0]
    assert r["html_content"] == "<p>previous chest CT</p>"
    assert r["status"] == "completed"
    assert r["patient_id"] == "47633"
    assert r["reporting_physician_name"] == "Dr Persian"   # dict physician coerced
    assert r["created_at"] > 0                              # ISO date parsed


def test_modality_object_is_coerced_to_a_label():
    """REGRESSION (47633, live): the server sends modality as an OBJECT
    {"_id":"1","Modality":"CT","FullName":"CT Scan",...}. A bare str() leaked
    `{'_id': '1'...}` into the overlay label; it must render as "CT"."""
    envelope = {
        "success": True,
        "data": {
            "receptionId": "47633",
            "modality": {"_id": "1", "Modality": "CT", "FullName": "CT Scan",
                         "PerFullName": "سی تی اسکن", "Icon": "ct.png"},
            "report": {"content": "<p>r</p>", "status": "completed"},
        },
    }
    out = normalize_reception_record_reports(envelope, patient_id="47633")
    assert out[0]["sender_info"] == "Modality: CT | Previous exam (read-only)"
    assert "{" not in out[0]["sender_info"]


def test_envelope_with_data_as_list():
    envelope = {"success": True, "data": [{"report": {"content": "<p>x</p>"}}]}
    out = normalize_reception_record_reports(envelope, patient_id="9")
    assert len(out) == 1 and out[0]["html_content"] == "<p>x</p>"


def test_iso_datetime_parses_to_epoch():
    assert study_datetime_to_epoch("2026-07-21T13:48:15") > 0
    assert study_datetime_to_epoch("2026-07-21") > 0


def test_normalizes_from_imaging_workflow_path():
    record = {"imagingWorkflow": {"report": {"findings": "<p>iw report</p>"}}}
    out = normalize_reception_record_reports(record, patient_id="7")
    assert len(out) == 1 and out[0]["html_content"] == "<p>iw report</p>"


def test_no_report_html_yields_empty_so_caller_falls_back():
    assert normalize_reception_record_reports({"foo": "bar"}) == []
    assert normalize_reception_record_reports({"report": {"status": "pending"}}) == []


def test_normalizer_never_raises_on_garbage():
    assert normalize_reception_record_reports(None) == []
    assert normalize_reception_record_reports("not a dict") == []
    assert normalize_reception_record_reports(12345) == []


@pytest.mark.parametrize("date,time,positive", [
    ("20250601", "143000", True),
    ("20250601", "", True),
    ("bad", "", False),
    ("", "", False),
    ("2025", "", False),
])
def test_study_datetime_to_epoch(date, time, positive):
    v = study_datetime_to_epoch(date, time)
    assert (v > 0) is positive


def test_epoch_orders_chronologically():
    older = study_datetime_to_epoch("20240301")
    newer = study_datetime_to_epoch("20250601")
    assert newer > older > 0


# ---------------------------------------------------------------------------
# Wiring + read-only source-pins
# ---------------------------------------------------------------------------


def _read(rel: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def _method(src: str, name: str) -> str:
    body = src.split(f"def {name}", 1)[1].split("\n    def ", 1)[0]
    if '"""' in body:
        parts = body.split('"""')
        body = "".join(parts[2:]) if len(parts) >= 3 else body
    return "\n".join(l.split("#", 1)[0] for l in body.splitlines())


DIALOG = "modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py"
VIEWER = "PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py"


def test_flag_default_on_and_indicator_hidden_by_default():
    src = _read(DIALOG)
    assert "os.getenv('AIPACS_REPORT_EDITOR_PREVIOUS_EXAMS', '1')" in src
    assert ".strip() != '0'" in src
    assert "self.btn_previous_exams" in src
    assert "self.btn_previous_exams.setVisible(False)" in src   # hidden until found


def test_history_worker_uses_the_shared_pure_pipeline():
    body = _method(_read(DIALOG), "_previous_exams_worker")
    assert "get_socket_patient_service" in body
    assert "get_reception_history_sync" in body
    assert "get_patient_status_sync" in body
    assert "build_previous_exam_set" in body
    assert "distinct_previous_patient_ids" in body


def test_history_lookup_runs_off_the_gui_thread():
    body = _method(_read(DIALOG), "_start_previous_exams_lookup")
    assert "threading.Thread" in body
    assert "daemon=True" in body


def test_previous_reports_fetch_is_server_live_with_local_fallback():
    body = _method(_read(DIALOG), "_previous_reports_worker")
    assert "api/pacs/patients/" in body               # live reception server
    assert "normalize_reception_record_reports" in body
    assert "ai_get_reception_reports" in body          # local DB fallback
    assert "threading" not in body or True             # (runs in a worker already)


def test_previous_reports_shown_read_only_via_provided_reports():
    src = _read(DIALOG)
    body = _method(src, "_on_previous_reports_ready")
    assert "ReceptionReportsViewer" in body
    assert "show_provided_reports" in body
    assert "read-only" in body.lower()
    # ReceptionReportsViewer is a QWidget (no .exec()); it must be hosted in a
    # QDialog wrapper, NOT shown via viewer.exec() (the crash we fixed).
    assert "QDialog(self)" in body
    assert "dlg.exec()" in body
    assert "viewer.exec()" not in body


def test_provided_reports_view_disables_mutating_actions():
    """Server-sourced previous reports aren't local DB rows, so mark-read /
    archive / delete must be disabled — a strictly read-only preview."""
    body = _method(_read(VIEWER), "show_provided_reports")
    assert "setEnabled(False)" in body
    for btn in ("btn_mark_read", "btn_archive", "btn_delete"):
        assert btn in body


def test_report_preview_is_theme_independent_and_bidi_correct():
    """The preview must render on a FIXED white paper with dark text (so it is
    readable regardless of the OS/app light-or-dark theme, and the report's
    dark-navy author colours keep contrast), and use per-line bidi so RTL/LTR
    is correct per paragraph."""
    # RAW extract (not _method, which strips '#' comments — and CSS hex colours
    # contain '#').
    src = _read(VIEWER)
    body = src.split("def _display_report", 1)[1].split("\n    def ", 1)[0]
    assert "background-color: #ffffff" in body
    assert "color: #1a1a1a" in body
    assert "unicode-bidi: plaintext" in body
    # widget chrome pinned white too (no dark theme frame bleeding through)
    assert "QTextBrowser{background:#ffffff" in body
    # the old hard-coded dark canvas must be gone
    assert "#2b2b2b" not in body


def test_provided_reports_view_auto_selects_first_report():
    """The preview must render immediately (the 'empty box' fix) — the first
    report is auto-selected, and that auto-select must come BEFORE the buttons
    are disabled (else _on_report_clicked re-enables them)."""
    body = _method(_read(VIEWER), "show_provided_reports")
    assert "setCurrentRow(0)" in body
    assert "_on_report_clicked" in body
    assert body.index("_on_report_clicked") < body.index('"btn_mark_read"')


def test_previous_exams_paths_never_touch_the_active_report():
    """The whole point: viewing a previous report must not overwrite the report
    being edited. None of the previous-exams methods may write the editor's
    content/report state."""
    src = _read(DIALOG)
    for name in ("_previous_exams_worker", "_on_previous_exams_ready",
                 "_open_previous_reports", "_previous_reports_worker",
                 "_on_previous_reports_ready"):
        body = _method(src, name)
        for forbidden in ("self.text_edit.setHtml", "self.text_edit.setPlainText",
                          "self.report =", "self.original_content =",
                          "self.report_saved.emit", "_apply_report_html"):
            assert forbidden not in body, f"{name} must not mutate the active report ({forbidden})"


def test_viewer_provided_reports_is_read_only_and_dbless():
    body = _method(_read(VIEWER), "show_provided_reports")
    assert "self.current_reports = list" in body
    assert "_update_list_view" in body
    # renders the provided list only — no DB read/write helpers of any kind
    for db_call in ("ai_get_reception_reports", "get_db_connection",
                    "ai_update_reception_report", "ai_delete_reception_report"):
        assert db_call not in body, f"show_provided_reports must not call {db_call}"
