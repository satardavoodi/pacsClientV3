"""Validation of the mode-aware sync policy (docs/architecture/SYNC_MODE_SEPARATION.md).

Encodes the directive's per-mode contract as assertions: only LiveServer treats the
server as source of truth and runs mandatory version-aware sync; LocalDatabase / Import /
OfflineServer / CDBurn are local/offline-first and must not be forced to verify against
the live ai-pacs server.
"""
import ast
import importlib
from pathlib import Path

import pytest

p = importlib.import_module("modules.storage.sync_mode_policy")
REPO = Path(__file__).resolve().parents[3]
HP_SERIES = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    monkeypatch.delenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", raising=False)


# ── mode resolution ──────────────────────────────────────────────────────────

def test_source_to_mode_mapping():
    assert p.resolve_workflow_mode("server") == p.WorkflowMode.LIVE_SERVER
    assert p.resolve_workflow_mode("db") == p.WorkflowMode.LOCAL_DATABASE
    assert p.resolve_workflow_mode("import") == p.WorkflowMode.IMPORT
    assert p.resolve_workflow_mode("offline_cloud") == p.WorkflowMode.OFFLINE_SERVER
    assert p.resolve_workflow_mode(None) == p.WorkflowMode.UNKNOWN
    assert p.resolve_workflow_mode("garbage") == p.WorkflowMode.UNKNOWN
    # accepts a WorkflowMode value too
    assert p.resolve_workflow_mode(p.WorkflowMode.LIVE_SERVER) == p.WorkflowMode.LIVE_SERVER


# ── LiveServer: server is source of truth, strict version-aware sync ──────────

def test_live_server_is_strict():
    for fn in (p.requires_live_server_sync, p.requires_remote_resync,
               p.requires_server_version_check, p.missing_files_trigger_server_download):
        assert fn("server") is True, fn.__name__
    assert p.local_is_source_of_truth("server") is False
    assert p.can_trust_local_cache_as_authoritative("server") is False


# ── LocalDatabase: strict local by default; server refresh is opt-in/manual ───

def test_local_database_does_not_sync_by_default():
    assert p.local_is_source_of_truth("db") is True          # local = display truth
    assert p.can_trust_local_cache_as_authoritative("db") is True
    assert p.requires_remote_resync("db") is False
    assert p.requires_live_server_sync("db") is False
    assert p.requires_server_version_check("db") is False
    assert p.missing_files_trigger_server_download("db") is False


def test_local_database_opt_in_flag_enables_auto_sync(monkeypatch):
    monkeypatch.setenv("AIPACS_LOCALDB_AUTO_SERVER_SYNC", "1")
    assert p.requires_remote_resync("db") is True
    assert p.requires_live_server_sync("db") is True
    assert p.missing_files_trigger_server_download("db") is True
    assert p.local_is_source_of_truth("db") is True


# ── Import: purely local files, never live sync ──────────────────────────────

def test_import_never_live():
    assert p.local_is_source_of_truth("import") is True
    assert p.requires_live_server_sync("import") is False
    assert p.requires_remote_resync("import") is False
    assert p.requires_server_version_check("import") is False
    assert p.missing_files_trigger_server_download("import") is False


# ── OfflineServer: offline-cloud rules, not live-ai-pacs rules ────────────────

def test_offline_server_resyncs_cloud_not_live():
    # offline-cloud keeps its own remote (cloud) resync ...
    assert p.requires_remote_resync("offline_cloud") is True
    # ... but is NOT a live ai-pacs server workflow and local is its truth.
    assert p.requires_live_server_sync("offline_cloud") is False
    assert p.local_is_source_of_truth("offline_cloud") is True
    assert p.missing_files_trigger_server_download("offline_cloud") is False


# ── Unknown: resync runs (no regression) but is not assumed live-server ───────

def test_unknown_runs_resync_but_not_assumed_live_server():
    # The resync is permissive for an unclassified source (it ran for every source
    # before this work; a not-yet-known patient must keep resyncing and degrade
    # gracefully). The stricter predicates do NOT assume a live-server workflow.
    assert p.requires_remote_resync(None) is True
    assert p.requires_live_server_sync(None) is False
    assert p.requires_server_version_check(None) is False
    assert p.local_is_source_of_truth(None) is True


# ── logging never raises, never needs credentials ────────────────────────────

def test_log_mode_decision_is_safe():
    import logging
    logger = logging.getLogger("test.syncmode")
    # must not raise on any input
    p.log_mode_decision(logger, source="server", study_uid="1.2.3",
                        local_version=5, server_version=7, sync_skipped=False,
                        reason="grew", changed="series 9")
    p.log_mode_decision(logger, source=None)


# ── the resync adopts the policy (source guard) ──────────────────────────────

def test_resync_uses_policy_gate():
    src = HP_SERIES.read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_resync_patient_studies_from_server"), None)
    assert fn is not None
    body = ast.get_source_segment(src, fn)
    assert "requires_remote_resync" in body          # gated by the policy
    assert "if not force:" in body                    # only the AUTO path is gated
    assert "log_mode_decision" in body or "_log_mode" in body  # logs the skip
