"""Guard: a SERVER-PROFILE (centre) switch must force a restart, never a live rebind.

Why this test exists
--------------------
The clinical data root is per-profile (``user_data/servers/<slug>``), but ~33
production modules bind ``SOURCE_PATH`` / ``THUMBNAIL_PATH`` / ``ATTACHMENT_PATH``
**by value** at import time, all of them imported before the login screen exists.
``database/_pool.py`` resolves ``DATABASE_FILE`` with an *in-function* import and
therefore DOES follow a rebind. So a runtime centre switch produces the
asymmetric state — DB on centre B, DICOM/thumbnails/attachments on centre A —
which is a clinical data-integrity defect, not a cosmetic one.

These assertions pin the contract, the kill switch, and the two structural facts
the contract rests on.
"""

import ast
import importlib
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


@pytest.fixture()
def refresh_mod(monkeypatch):
    monkeypatch.delenv("AIPACS_PROFILE_SWITCH_RESTART", raising=False)
    sys.modules.pop("modules.network.runtime_server_refresh", None)
    return importlib.import_module("modules.network.runtime_server_refresh")


# ── the contract ────────────────────────────────────────────────────────────

def test_profile_switch_returns_restart_required(refresh_mod):
    assert (
        refresh_mod.apply_saved_server_settings_runtime(profile_switched=True)
        == refresh_mod.RESTART_REQUIRED
    )


def test_profile_switch_does_not_rebind_paths_or_drop_the_pool(refresh_mod, monkeypatch):
    """The unsafe trio must not run on the default (restart) path."""
    called = []

    import PacsClient.utils.data_paths as dp

    monkeypatch.setattr(
        dp, "reload_active_profile_paths", lambda: called.append("paths"), raising=False
    )
    import database.core as dbcore

    monkeypatch.setattr(
        dbcore, "cleanup_connection_pools", lambda: called.append("pool"), raising=False
    )

    refresh_mod.apply_saved_server_settings_runtime(profile_switched=True)
    assert called == [], f"a centre switch must not touch {called} in-process"


def test_kill_switch_restores_the_legacy_runtime_rebind(monkeypatch):
    monkeypatch.setenv("AIPACS_PROFILE_SWITCH_RESTART", "0")
    sys.modules.pop("modules.network.runtime_server_refresh", None)
    mod = importlib.import_module("modules.network.runtime_server_refresh")
    assert mod._restart_on_profile_switch() is False


def test_same_profile_edit_still_applies_live(refresh_mod):
    """The genuine improvement in the branch must survive: no restart for a
    host/port/timeout edit on the ACTIVE centre."""
    assert (
        refresh_mod.apply_saved_server_settings_runtime(profile_switched=False)
        == refresh_mod.APPLIED
    )


def test_never_raises(refresh_mod, monkeypatch):
    import modules.network.socket_config as sc

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(sc, "get_socket_config", _boom, raising=False)
    assert refresh_mod.apply_saved_server_settings_runtime(profile_switched=False)


# ── the structural facts the contract rests on ──────────────────────────────

_BY_VALUE_NAMES = {"SOURCE_PATH", "THUMBNAIL_PATH", "ATTACHMENT_PATH", "DATABASE_PATH"}


def _module_scope_by_value_importers() -> list[str]:
    hits = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & {".venv", ".venv_build", "backups", "_recovery", "generated-files"}:
            continue
        if "builder" in parts or "tests" in parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:  # module scope ONLY — an in-function import is safe
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "PacsClient.utils.config"
                and any(a.name in _BY_VALUE_NAMES for a in node.names)
            ):
                hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


def test_the_by_value_snapshot_problem_is_real_and_unfixed():
    """If this ever drops to zero, a runtime centre switch becomes feasible and
    this whole guard should be revisited — deliberately, not by accident."""
    hits = _module_scope_by_value_importers()
    assert len(hits) > 10, (
        "module-scope by-value importers of the clinical paths have largely "
        f"disappeared ({len(hits)} left) — re-evaluate the restart requirement"
    )


def test_the_database_does_follow_a_rebind():
    """The other half of the asymmetry: _pool resolves DATABASE_FILE per call."""
    pool_src = _read("database/_pool.py")
    assert "from PacsClient.utils.data_paths import DATABASE_FILE" in pool_src
    tree = ast.parse(pool_src)
    module_level = [
        n
        for n in tree.body
        if isinstance(n, ast.ImportFrom)
        and n.module == "PacsClient.utils.data_paths"
        and any(a.name == "DATABASE_FILE" for a in n.names)
    ]
    assert not module_level, "DATABASE_FILE must stay an in-function import"


# ── caller wiring ───────────────────────────────────────────────────────────

def test_login_gear_quits_on_restart_required():
    src = _read("PacsClient/app_handler.py")
    assert "RESTART_REQUIRED" in src
    assert "_quit_for_profile_switch" in src
    assert "app.quit()" in src


def test_login_window_still_restarts_on_centre_change():
    src = _read("PacsClient/login/ui/login_ui.py")
    assert "AI-PACS will now close" in src
    assert "QApplication.quit()" in src


def test_runtime_refresh_does_not_reach_into_private_db_pool():
    src = _read("modules/network/runtime_server_refresh.py")
    assert "from database._pool import" not in src
    assert "from database.core import cleanup_connection_pools" in src


def test_runtime_refresh_does_not_construct_the_patient_service():
    """get_socket_patient_service() CONSTRUCTS on first call; at the login screen
    that would spin up a service the session does not need."""
    src = _read("modules/network/runtime_server_refresh.py")
    assert "get_socket_patient_service()" not in src
    assert '_socket_patient_service", None' in src
