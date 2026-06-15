"""Source-level guards for the contentVersion sync wiring (2026-06-15).

These assert the integration points stay in place across refactors without
importing the heavy Qt home-panel mixin. Behaviour of the store itself is covered
by test_content_version_store.py. The contract under guard:

  capture  : series_utils + get_series_info_from_server + get_study_thumbnails all
             surface server content_version into the study_info / data dict.
  gate     : the resync reads content_version, cheap-skips when unchanged
             (result='current_cv'), but NEVER cheap-skips a forced refresh, and
             stamps the synced version ONLY on the confirmed-complete branch.
  flag     : AIPACS_CONTENT_VERSION_SYNC defaults ON and is independently revertible.
  clear    : deleting a patient forgets its synced contentVersion.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _read(rel):
    # utf-8-sig: some home-panel files carry a BOM that trips ast.parse otherwise.
    return (REPO / rel).read_text(encoding="utf-8-sig")


def _func_src(tree_src, func_name):
    """Return the source segment of a top-level or method function by name."""
    tree = ast.parse(tree_src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(tree_src, node)
    return None


# ── capture points ──────────────────────────────────────────────────────────

def test_series_utils_captures_content_version():
    src = _func_src(_read("modules/network/series_utils.py"),
                    "extract_series_info_from_grpc_response")
    assert src is not None
    assert "'content_version'" in src
    assert "getattr(grpc_response, 'content_version'" in src
    # Casing-robust: must also accept the server's camelCase spelling.
    assert "contentVersion" in src


def test_get_study_thumbnails_surfaces_content_version():
    src = _func_src(_read("modules/network/socket_client.py"), "get_study_thumbnails")
    assert src is not None
    assert 'content_version' in src
    assert 'response.get("content_version")' in src
    # Casing-robust: must also accept the server's camelCase spelling.
    assert 'contentVersion' in src


def test_get_series_info_from_server_captures_content_version():
    src = _func_src(_read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_study_save.py"),
                    "get_series_info_from_server")
    assert src is not None
    assert "'content_version'" in src
    assert "response.get('content_version')" in src
    # Casing-robust: must also accept the server's camelCase spelling.
    assert "response.get('contentVersion')" in src


# ── resync gate ──────────────────────────────────────────────────────────────

def test_resync_reads_and_gates_on_content_version():
    src = _func_src(_read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"),
                    "_resync_patient_studies_from_server")
    assert src is not None
    # reads server content_version
    assert "get('content_version')" in src
    # cheap-skip branch with the dedicated trace result
    assert "result='current_cv'" in src
    # cheap-skip is gated by the flag AND must never fire on a forced refresh
    assert "_RESYNC_USE_CONTENT_VERSION" in src
    assert "and not force" in src
    # stamps the synced version (confirmed-complete branch only)
    assert "set_synced_version" in src


def test_resync_auto_path_gated_by_mode_policy():
    """The AUTO resync is gated by the mode-aware policy (requires_remote_resync):
    LiveServer + OfflineServer run, Import/CD/unknown never, LocalDatabase only with
    the opt-in flag. A forced/manual refresh (force=True) is never gated."""
    src = _func_src(_read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"),
                    "_resync_patient_studies_from_server")
    assert src is not None
    assert "requires_remote_resync" in src
    # Only the auto path is gated; a manual force=True refresh always runs.
    pos = src.index("requires_remote_resync")
    assert "if not force:" in src[:pos]
    # The policy itself enforces the per-mode contract (covered in detail by
    # test_sync_mode_policy); sanity-check the two endpoints here.
    from modules.storage.sync_mode_policy import requires_remote_resync
    assert requires_remote_resync("import") is False
    assert requires_remote_resync("server") is True


def test_resync_stamps_only_on_complete_branch_not_enqueue():
    """The set_synced_version call must sit on the `not needs_sync` (complete)
    branch, never alongside the dm.add_downloads enqueue — recording a version we
    have not finished downloading would pin an incomplete study as current."""
    src = _func_src(_read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"),
                    "_resync_patient_studies_from_server")
    assert src is not None
    set_idx = src.index("set_synced_version")
    enqueue_idx = src.index("dm.add_downloads")
    not_needs_idx = src.index("if not needs_sync:")
    # stamp appears after the `if not needs_sync:` guard and before the enqueue
    assert not_needs_idx < set_idx < enqueue_idx


def test_content_version_flag_defaults_on_and_revertible():
    src = _read("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py")
    assert "_RESYNC_USE_CONTENT_VERSION" in src
    assert "AIPACS_CONTENT_VERSION_SYNC" in src
    # default '1' + the standard falsy-set parse => default ON, flippable to off.
    assert "'AIPACS_CONTENT_VERSION_SYNC', '1'" in src
    assert "not in ('0', 'false', 'no', 'off')" in src


# ── clear-on-delete wiring ───────────────────────────────────────────────────

def test_patient_cleanup_clears_content_version():
    src = _func_src(_read("modules/storage/patient_cleanup_manager.py"),
                    "delete_patient_completely")
    assert src is not None
    assert "content_version_store" in src
    assert "clear" in src


# ── store API smoke (import-light) ───────────────────────────────────────────

def test_store_exposes_expected_api():
    import importlib
    mod = importlib.import_module("modules.storage.content_version_store")
    for name in ("get_synced_version", "set_synced_version", "clear", "_store_path",
                 "_reset_cache_for_tests"):
        assert hasattr(mod, name), name
