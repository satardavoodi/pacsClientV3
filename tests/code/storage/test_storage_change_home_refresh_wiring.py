"""Guard the storage-clear -> home patient-list refresh signal chain (2026-06-14).

Bug class: clearing DICOM files from Settings -> Viewer Configuration ->
Information Storage deleted the files but the home patient table kept showing the
study as downloaded/green, because the panel's ``storageChanged`` signal was
emitted but nothing was connected to it.

The fix connects ``StorageCleanupPanelWidget.storageChanged`` (reached through the
lazily-built viewer-config tab) to a home-table refresh that recomputes each
study's status from disk (the source of truth). This is a static source guard so
the end-to-end chain can't be silently broken without instantiating the full Qt
app. Each link is asserted independently.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_WS_UI = _REPO / "PacsClient" / "pacs" / "workstation_ui"
_AIPACS_UI = _WS_UI / "AIPacs_ui.py"
_VIEWER_CFG = _WS_UI / "settings_ui" / "viewerconfigsetting.py"
_PANEL = _WS_UI / "settings_ui" / "storage_cleanup_panel.py"
_TABLE = _WS_UI / "home_ui" / "patient_table_widget.py"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _func_body_src(tree: ast.Module, name: str, source: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _func_exec_src(tree: ast.Module, name: str, source: str) -> str:
    """Source of a function's body EXCLUDING its docstring, so 'X not in body'
    checks test the executable code and aren't fooled by prose in the docstring."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            stmts = node.body
            if (
                stmts
                and isinstance(stmts[0], ast.Expr)
                and isinstance(getattr(stmts[0], "value", None), ast.Constant)
                and isinstance(stmts[0].value.value, str)
            ):
                stmts = stmts[1:]
            return "\n".join(
                seg for seg in (ast.get_source_segment(source, s) for s in stmts) if seg
            )
    return ""


def test_panel_declares_and_emits_storage_changed():
    src = _src(_PANEL)
    assert "storageChanged = Signal()" in src, "panel must declare storageChanged"
    # Emitted on the clear paths (patient clear / cache clear / dialog clear).
    assert src.count("self.storageChanged.emit()") >= 2, (
        "clear actions must emit storageChanged so the rest of the app can refresh"
    )


def test_viewer_config_exposes_storage_panel():
    src = _src(_VIEWER_CFG)
    assert "self.storage_cleanup_panel = StorageCleanupPanelWidget()" in src, (
        "ModalityGridConfigWidget must expose storage_cleanup_panel for wiring"
    )


def test_aipacs_ui_wires_storage_changed_to_home_refresh():
    src = _src(_AIPACS_UI)
    tree = ast.parse(src)

    wire = _func_body_src(tree, "_wire_modality_grid_config_signal", src)
    assert wire, "_wire_modality_grid_config_signal must exist"
    assert "storage_cleanup_panel" in wire, (
        "wiring hook must reach the panel via the (lazy) viewer-config tab"
    )
    assert "storageChanged.connect(self._on_storage_changed_refresh_home)" in wire, (
        "storageChanged must be connected to the home-refresh handler"
    )

    handler = _func_body_src(tree, "_on_storage_changed_refresh_home", src)
    assert handler, "_on_storage_changed_refresh_home handler must exist"
    assert "refresh_download_statuses_local_only()" in handler, (
        "handler must prefer the focused local-only refresh (no server call)"
    )
    # Must be defensively guarded (runs from a UI signal; must never raise).
    assert "try:" in handler and "except Exception" in handler


def test_home_refresh_recomputes_status_from_disk():
    """The refresh must invalidate the cache so status is recomputed from disk,
    not served stale (otherwise a cleared study stays green)."""
    src = _src(_TABLE)
    tree = ast.parse(src)
    body = _func_body_src(tree, "refresh_download_statuses", src)
    assert body, "patient table must expose refresh_download_statuses"
    assert "_download_status_cache.clear()" in body, (
        "refresh must clear the in-memory status cache so disk is re-checked"
    )


def test_local_only_refresh_recomputes_from_disk_without_server_pull():
    """Conservative storage-clear refresh: recompute green/downloaded badges from
    disk but with the smallest possible blast radius — no server report re-pull,
    no refresh-button animation."""
    src = _src(_TABLE)
    tree = ast.parse(src)
    assert _func_body_src(tree, "refresh_download_statuses_local_only", src), (
        "patient table must expose refresh_download_statuses_local_only"
    )
    # Check the executable body (docstring excluded) so the negative assertions
    # below test the code, not the method's prose.
    body = _func_exec_src(tree, "refresh_download_statuses_local_only", src)
    assert "_download_status_cache.clear()" in body, (
        "local-only refresh must clear the status cache so disk is re-checked"
    )
    assert "update_study_download_status(" in body, (
        "local-only refresh must recompute each row's status from disk"
    )
    # Conservative guarantees (the whole point of the local-only variant):
    assert "reportRefreshRequested" not in body, (
        "local-only refresh must NOT emit reportRefreshRequested (no server call)"
    )
    assert "animate_refresh" not in body and "refresh_btn" not in body, (
        "local-only refresh must NOT run the refresh-button animation"
    )
