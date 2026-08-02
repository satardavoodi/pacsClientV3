"""Local Patient-ID correction alias (2026-07-29).

A reception typo (e.g. server ``52659`` for the correct ``52658``) is corrected
locally via right-click ▸ Edit. The AI-PACS server has NO demographic-write
endpoint, so it keeps returning the original ID. ``database.patient_overrides``
records a display-only alias ``original_server_id -> corrected_id`` and the
patient-list Patient-ID column PAINTS the corrected value while the cell's
identity (``.text()`` / DisplayRole) stays the server's original key — so every
server-directed read (assignment ``reception_id``, reception payload, report
status, open) keeps using the real key.

Authority behaviour is unit-tested against a temp SQLite DB (``_db_conn``
monkeypatched, per identity_db's documented test seam). The Qt paint delegate +
wiring are source-pinned (paint behaviour is not unit-renderable headless).
"""
import contextlib
import sqlite3
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


# ── authority fixture: isolated temp DB via the documented _db_conn seam ──────

@pytest.fixture
def po(tmp_path, monkeypatch):
    import database.patient_overrides as po

    db_path = tmp_path / "overrides.db"

    @contextlib.contextmanager
    def _fake_conn():
        conn = sqlite3.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(po, "_db_conn", _fake_conn)
    po._schema_ready = False
    po.invalidate_cache()
    monkeypatch.setenv("AIPACS_PATIENT_ID_OVERRIDES", "1")  # display enabled
    try:
        yield po
    finally:
        po.invalidate_cache()
        po._schema_ready = False


# ── authority behaviour ──────────────────────────────────────────────────────

def test_set_then_resolve_shows_corrected(po):
    assert po.set_patient_id_override("52659", "52658", corrected_patient_name="mohamad") is True
    assert po.resolve_display_patient_id("52659") == "52658"
    # the map exposes it too
    assert po.all_patient_id_overrides().get("52659") == "52658"


def test_resolve_is_none_when_flag_off(po, monkeypatch):
    po.set_patient_id_override("52659", "52658")
    monkeypatch.setenv("AIPACS_PATIENT_ID_OVERRIDES", "0")
    # display gate closed -> caller falls back to the server's original ID
    assert po.resolve_display_patient_id("52659") is None


def test_flag_defaults_off(po, monkeypatch):
    monkeypatch.delenv("AIPACS_PATIENT_ID_OVERRIDES", raising=False)
    assert po.patient_overrides_enabled() is False


def test_unknown_id_resolves_none(po):
    po.set_patient_id_override("52659", "52658")
    assert po.resolve_display_patient_id("99999") is None


def test_no_op_on_equal_or_blank(po):
    assert po.set_patient_id_override("52658", "52658") is False   # equal
    assert po.set_patient_id_override("", "52658") is False        # blank orig
    assert po.set_patient_id_override("52659", "") is False        # blank corrected
    assert po.all_patient_id_overrides() == {}


def test_update_existing_alias(po):
    po.set_patient_id_override("52659", "52658")
    po.set_patient_id_override("52659", "52660")  # re-correct
    assert po.resolve_display_patient_id("52659") == "52660"
    row = po.get_patient_id_override("52659")
    assert row["corrected_patient_id"] == "52660"


def test_clear_removes_alias(po):
    po.set_patient_id_override("52659", "52658")
    assert po.clear_patient_id_override("52659") is True
    assert po.resolve_display_patient_id("52659") is None
    assert po.clear_patient_id_override("52659") is False  # already gone


def test_name_alias_optional(po):
    po.set_patient_id_override("52659", "52658")  # no name
    assert po.resolve_display_patient_name("52659") is None
    po.set_patient_id_override("52659", "52658", corrected_patient_name="mohamad moradian")
    assert po.resolve_display_patient_name("52659") == "mohamad moradian"


def test_cache_coherent_across_set_and_clear(po):
    # prime the cache
    assert po.resolve_display_patient_id("52659") is None
    po.set_patient_id_override("52659", "52658")
    assert po.resolve_display_patient_id("52659") == "52658"  # cache updated in place
    po.clear_patient_id_override("52659")
    assert po.resolve_display_patient_id("52659") is None


# ── source-pins: delegate is DISPLAY-ONLY, identity untouched ─────────────────

def _ptw_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "patient_table_widget.py").read_text(encoding="utf-8")


def test_delegate_exists_and_is_display_only():
    src = _ptw_src()
    assert "class _PatientIdOverrideDelegate(CombinedDelegate):" in src
    body = src[src.find("class _PatientIdOverrideDelegate"):]
    body = body[:body.find("\nCOL = {")]
    # it only adjusts the transient painted option.text
    assert "resolve_display_patient_id(option.text)" in body
    assert "option.text = corrected" in body
    # it must NOT mutate the model / cell identity
    assert "setData" not in body
    assert "setText" not in body
    assert "setItem" not in body


def test_delegate_installed_on_patient_id_column():
    src = _ptw_src()
    setup = src[src.find("def _setup_neon_highlight_delegate"):]
    setup = setup[:setup.find("\n    def _on_header_clicked")]
    assert "if col == COL['patient_id']:" in setup
    assert "_PatientIdOverrideDelegate(" in setup


# ── source-pins: edit records the alias; dialog carries reception guidance ────

def test_edit_records_alias_on_patient_id_change():
    src = (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
           / "home_panel" / "_hp_patient_edit.py").read_text(encoding="utf-8")
    assert "set_patient_id_override(" in src
    # guarded by an actual change of the ID
    assert 'str(new_patient_id).strip() != str(patient_id_before or "").strip()' in src


def test_dialog_has_reception_system_of_record_guidance():
    src = (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
           / "patient_edit_dialog.py").read_text(encoding="utf-8")
    assert "system of record" in src
    assert "reception fix it at admission" in src
