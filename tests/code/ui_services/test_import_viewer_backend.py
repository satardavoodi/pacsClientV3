"""Guard: the tab auto-opened after an external import uses the SAME viewer
backend as normal patient-open (the FAST ``QtFastContainer`` by default), NOT the
deprecated VTK ``pydicom_2d`` backend.

ROOT CAUSE (fixed 2026-06-28 — "import opens an older/slower Patient Tab"):
``_HPImportMixin._open_imported_primary_study`` hard-pinned
``viewer_backend_override=BACKEND_PYDICOM`` ("pydicom_2d"), a stale v2.3.1
leftover.  v2.3.3 made ``BACKEND_PYDICOM_QT`` (the VTK-free FAST viewer) the
default for every other open path and deprecated ``pydicom_2d``.  The import pin
bypassed the ``resolve_viewer_backend()`` remap (see
``_vc_backend._get_requested_viewer_backend``), so a freshly imported study
opened in the legacy ``VTKWidget`` viewer while reopening the same study from the
patient list used the FAST ``QtFastContainer``.  The fix drops the default
override and keeps a kill switch (``AIPACS_IMPORT_FORCE_LEGACY_VIEWER=1``) for
rollback.

Driven through a fake ``self`` — no Qt stand-up.
"""
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
IMPORT_PY = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_import.py"


def _drive_open(monkeypatch, env_value=None):
    """Call ``_open_imported_primary_study`` with a fake self; return captured kwargs."""
    from PacsClient.pacs.workstation_ui.home_ui.home_panel._hp_import import _HPImportMixin

    if env_value is None:
        monkeypatch.delenv("AIPACS_IMPORT_FORCE_LEGACY_VIEWER", raising=False)
    else:
        monkeypatch.setenv("AIPACS_IMPORT_FORCE_LEGACY_VIEWER", env_value)

    captured = {}

    def fake_add_new_tab_widget(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    fake_self = SimpleNamespace(
        data_access_panel_widget=SimpleNamespace(
            folder_path_label=SimpleNamespace(setText=lambda *_a, **_k: None)
        ),
        add_new_tab_widget=fake_add_new_tab_widget,
    )

    _HPImportMixin._open_imported_primary_study(
        fake_self,
        {"study_uid": "1.2.3", "patient_id": "PID-1", "patient_name": "Imported X"},
    )
    return captured


def test_import_opens_with_default_backend(monkeypatch):
    """Default (no kill switch): no override -> import resolves the SAME backend
    as normal patient-open (FAST QtFastContainer by default)."""
    captured = _drive_open(monkeypatch, env_value=None)
    assert "viewer_backend_override" in captured
    assert captured["viewer_backend_override"] is None
    # The rest of the open contract is unchanged.
    assert captured["study_uid"] == "1.2.3"
    assert captured["caller"] == "import"  # CallerTypes.IMPORT
    assert captured["enable_progressive_mode"] is True


def test_kill_switch_off_value_still_default(monkeypatch):
    """An explicit '0' must behave exactly like unset (default FAST)."""
    captured = _drive_open(monkeypatch, env_value="0")
    assert captured["viewer_backend_override"] is None


def test_kill_switch_restores_legacy_pydicom_backend(monkeypatch):
    """AIPACS_IMPORT_FORCE_LEGACY_VIEWER=1 restores the legacy VTK pin."""
    from modules.viewer.viewer_backend_config import BACKEND_PYDICOM

    captured = _drive_open(monkeypatch, env_value="1")
    assert captured["viewer_backend_override"] == BACKEND_PYDICOM


def test_source_has_no_unconditional_legacy_pin():
    """Source guard: the unconditional v2.3.1 pin must be gone, replaced by the
    flag-gated kill switch."""
    src = IMPORT_PY.read_text(encoding="utf-8-sig")  # strip BOM for safety
    # Old unconditional call-site form must not reappear.
    assert "viewer_backend_override=BACKEND_PYDICOM," not in src
    # Kill switch + computed override must be present.
    assert "AIPACS_IMPORT_FORCE_LEGACY_VIEWER" in src
    assert "viewer_backend_override=viewer_backend_override," in src
