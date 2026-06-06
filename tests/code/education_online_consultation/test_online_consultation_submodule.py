"""Guards for the Education ▸ Online Consultation submodule (2026-06-06).

Qt-free: covers the availability gate, the clinical status-label mapping, and the
selection/export staging built on the EXISTING offline engine. The Qt page itself is
exercised live (it only composes these pieces).
"""

import sys
import types

import pytest

from modules.education.online_consultation import online_consultation_available
from modules.education.online_consultation.status_labels import (
    CONSULTATION_TAG,
    display_status,
    status_color,
)
from modules.education.online_consultation.study_select import (
    build_export_callable,
    build_selection,
)


# ── availability gate ─────────────────────────────────────────────────────────
def test_available_only_when_both_flags_on(monkeypatch):
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "1")
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", "1")
    assert online_consultation_available() is True


@pytest.mark.parametrize(
    "identity,cloud",
    [("0", "1"), ("1", "0"), ("0", "0")],
)
def test_unavailable_when_either_flag_off(monkeypatch, identity, cloud):
    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", identity)
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", cloud)
    assert online_consultation_available() is False


# ── status labels (Pending / Sent / Received / Answered / Closed) ─────────────
def test_every_internal_status_has_a_label_for_both_directions():
    from modules.cloud_consultation.consultation.models import ConsultationStatus

    for status in ConsultationStatus:
        for direction in ("outgoing", "incoming"):
            label = display_status(status.value, direction)
            assert label, (status, direction)
            assert status_color(label) and status_color(status.value, direction)


def test_direction_aware_lifecycle_mapping():
    assert display_status("pending", "outgoing") == "Pending"
    assert display_status("uploaded", "outgoing") == "Sent"
    assert display_status("uploaded", "incoming") == "Received"
    assert display_status("downloaded", "incoming") == "Received"
    assert display_status("answered", "outgoing") == "Answered"
    assert display_status("answered", "incoming") == "Answered"
    assert display_status("closed", "incoming") == "Closed"
    assert CONSULTATION_TAG == "Online Consultation"


def test_unknown_status_degrades_gracefully():
    assert display_status("weird_status") == "Weird_status"
    assert status_color("weird_status")  # falls back to a colour, never raises


# ── selection / export staging ────────────────────────────────────────────────
def _stub_offline_cloud(monkeypatch, result, calls):
    mod = types.ModuleType("PacsClient.utils.offline_cloud")

    def fake_export(server, study_uids, *, actor=None, source_server=None, operation="export"):
        calls.append({"server": server, "uids": list(study_uids),
                      "actor": actor, "operation": operation})
        return result

    mod.export_studies_to_offline_cloud = fake_export
    monkeypatch.setitem(sys.modules, "PacsClient.utils.offline_cloud", mod)


def test_build_selection_shape():
    rows = [
        {"study_uid": "1.2.3", "patient_name": "DOE^JOHN", "study_description": "Brain MRI"},
        {"study_uid": "4.5.6", "patient_name": "DOE^JOHN", "study_description": ""},
    ]
    sel = build_selection(rows, actor={"email": "a@x.com"})
    assert sel["study_uids"] == ["1.2.3", "4.5.6"]
    assert "2 study(ies)" in sel["label"]
    assert sel["default_title"] == "Brain MRI"
    assert callable(sel["export_callable"])


def test_export_callable_stages_via_offline_engine(monkeypatch, tmp_path):
    calls = []
    _stub_offline_cloud(monkeypatch, {"ok": True, "exported": 2, "errors": []}, calls)
    export = build_export_callable(["1.2.3", "4.5.6"], actor={"email": "a@x.com"})
    dest = tmp_path / "staging"
    assert export(str(dest)) == str(dest)
    assert calls and calls[0]["uids"] == ["1.2.3", "4.5.6"]
    assert calls[0]["server"]["folder_path"] == str(dest)
    assert calls[0]["operation"] == "consultation_export"


def test_export_callable_raises_on_engine_error(monkeypatch, tmp_path):
    calls = []
    _stub_offline_cloud(monkeypatch, {"ok": False, "exported": 0, "errors": ["disk full"]}, calls)
    export = build_export_callable(["1.2.3"])
    with pytest.raises(RuntimeError, match="disk full"):
        export(str(tmp_path / "x"))


def test_export_callable_rejects_empty_selection(tmp_path):
    export = build_export_callable([])
    with pytest.raises(RuntimeError, match="No studies"):
        export(str(tmp_path / "x"))
