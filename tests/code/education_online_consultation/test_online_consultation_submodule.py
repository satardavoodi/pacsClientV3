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


# ── module-registry gate (ADR-0003, 2026-06-10) ───────────────────────────────
def test_unavailable_when_module_registry_disables_consultation(monkeypatch):
    """Flags on but is_module_enabled('consultation') False → gate off."""
    import aipacs_runtime

    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "1")
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", "1")
    monkeypatch.setattr(
        aipacs_runtime, "is_module_enabled", lambda module_id, profile=None: False
    )
    assert online_consultation_available() is False


def test_registry_gate_fails_open(monkeypatch):
    """A broken registry read must NOT strip the flag-enabled feature."""
    import aipacs_runtime

    def boom(module_id, profile=None):
        raise RuntimeError("registry unavailable")

    monkeypatch.setenv("AIPACS_IDENTITY_MODULE", "1")
    monkeypatch.setenv("AIPACS_CLOUD_CONSULTATION", "1")
    monkeypatch.setattr(aipacs_runtime, "is_module_enabled", boom)
    assert online_consultation_available() is True


def test_consultation_is_in_module_catalog():
    """ADR-0003: the purchasable module is declared in the runtime catalog."""
    import aipacs_runtime

    catalog = {str(item["id"]): item for item in aipacs_runtime.MODULE_CATALOG}
    assert catalog["consultation"]["tier"] == "optional"
    assert catalog["consultation"]["default_enabled"] is False
    assert "modules/cloud_consultation" in catalog["consultation"]["package_sources"]
    # Identity ships core so the account/OAuth layer exists on every install.
    assert catalog["identity"]["tier"] == "basic"
    assert "modules/Identity" in catalog["identity"]["package_sources"]


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


# ── de-identification gate in the compose path (B3 / ADR-0003) ────────────────
def test_export_callable_deidentifies_by_default(monkeypatch, tmp_path):
    calls = []
    _stub_offline_cloud(monkeypatch, {"ok": True, "exported": 1, "errors": []}, calls)
    deid_calls = []

    from modules.cloud_consultation.consultation import deidentify as deid_mod

    def fake_deidentify(dest, **kwargs):
        deid_calls.append(dest)
        return deid_mod.DeidentifyResult(processed_files=1)

    monkeypatch.setattr(deid_mod, "deidentify_package", fake_deidentify)
    export = build_export_callable(["1.2.3"])
    dest = tmp_path / "staging"
    assert export(str(dest)) == str(dest)
    assert deid_calls == [str(dest)]


def test_export_callable_blocks_upload_when_deidentification_fails(monkeypatch, tmp_path):
    calls = []
    _stub_offline_cloud(monkeypatch, {"ok": True, "exported": 1, "errors": []}, calls)

    from modules.cloud_consultation.consultation import deidentify as deid_mod

    monkeypatch.setattr(
        deid_mod,
        "deidentify_package",
        lambda dest, **kwargs: deid_mod.DeidentifyResult(
            processed_files=0, excluded_files=2, warnings=["bad file"]
        ),
    )
    export = build_export_callable(["1.2.3"])
    with pytest.raises(RuntimeError, match="De-identification failed"):
        export(str(tmp_path / "x"))


def test_export_callable_deidentify_optout(monkeypatch, tmp_path):
    """deidentify=False (BAA-grade deployments only) skips the scrub step."""
    calls = []
    _stub_offline_cloud(monkeypatch, {"ok": True, "exported": 1, "errors": []}, calls)

    from modules.cloud_consultation.consultation import deidentify as deid_mod

    def explode(dest, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("deidentify_package must not be called when opted out")

    monkeypatch.setattr(deid_mod, "deidentify_package", explode)
    export = build_export_callable(["1.2.3"], deidentify=False)
    dest = tmp_path / "staging"
    assert export(str(dest)) == str(dest)
