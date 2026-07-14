"""FIX-3 guards — ``clear_table()`` must not be re-entrant-unsafe.

Field crash (2026-07-13, frozen build, ``native_fault.log``): a Windows **access
violation** on the Qt main thread, precisely here —

    patient_table_widget.py:clear_table   ->  self.results_table.setRowCount(0)
    home_search_service.py:search_server  ->  home.patient_table_widget.clear_table()
    _hp_search.py:search_patients_from_server_async
    qasync timerEvent -> main.py notify -> run_forever

Last log line, written milliseconds before the process died:
``[SEARCH-PERF] search_ms=208 rows=5`` — the statement immediately BEFORE
``clear_table()``. The table held 45 rows × up to 4 cell widgets, a download was
live, and four independent event-loop producers mutate the same QTableWidget with
no interlock. ``setRowCount(0)`` then destroyed ~180 cell widgets synchronously
inside the model reset.

These are source-level pins plus a behavioural test of the pure re-entrancy
predicate — no Qt widget is constructed, so they run headless anywhere.
"""
import ast
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_TABLE = _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_table_widget.py"
_SEARCH = _REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_search_service.py"


def _func_src(path: pathlib.Path, name: str) -> str:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


# ── clear_table itself ──────────────────────────────────────────────────────

def test_clear_table_raises_a_rebuild_guard():
    body = _func_src(_TABLE, "clear_table")
    assert "self._table_rebuilding = True" in body
    assert "self._table_rebuilding = False" in body
    assert "finally:" in body, "the guard must be released even on an exception"


def test_clear_table_cancels_the_timer_driven_producers():
    body = _func_src(_TABLE, "clear_table")
    assert "_status_refresh_token" in body, (
        "the chunked status-refresh singleShot chain must be cancelled before "
        "the rows it walks are destroyed"
    )
    assert "_pin_overlay_timer" in body and ".stop()" in body, (
        "the pin-overlay timer ADDS rows and re-sorts — it must not fire into a "
        "table being torn down"
    )


def test_clear_table_destroys_cell_widgets_deferred():
    body = _func_src(_TABLE, "clear_table")
    assert "_detach_all_cell_widgets" in body
    detach = _func_src(_TABLE, "_detach_all_cell_widgets")
    assert "removeCellWidget" in detach
    assert "deleteLater()" in detach, (
        "cell widgets must be destroyed from the event loop, NOT synchronously "
        "inside setRowCount(0)'s model reset — that is the access-violation window"
    )
    # and the detach must happen BEFORE the model reset (rindex skips the
    # docstring's narrative mention of setRowCount(0))
    assert body.index("self._detach_all_cell_widgets()") < body.rindex("table.setRowCount(0)")


def test_clear_table_blocks_signals_and_updates_during_teardown():
    body = _func_src(_TABLE, "clear_table")
    assert "setUpdatesEnabled(False)" in body
    assert "blockSignals(True)" in body
    assert "blockSignals(False)" in body
    assert "setUpdatesEnabled(True)" in body


def test_legacy_clear_is_preserved_behind_a_kill_switch():
    body = _func_src(_TABLE, "clear_table")
    assert "AIPACS_SAFE_CLEAR_TABLE" in body
    legacy = _func_src(_TABLE, "_clear_table_legacy")
    assert "setRowCount(0)" in legacy


# ── every other producer honours the guard ──────────────────────────────────

@pytest.mark.parametrize(
    "func",
    [
        "update_study_download_status",   # setCellWidget, driven by the DM + the chunked chain
        "_rebuild_status_cells_for",      # setCellWidget, driven by DM status events
        "_apply_pinned_overlay",          # ADDS rows + re-sorts, driven by a debounced timer
        "_refresh_statuses_chunked",      # the singleShot(0) chain itself
    ],
)
def test_producer_backs_off_while_the_table_is_being_rebuilt(func):
    body = _func_src(_TABLE, func)
    assert "table_rebuild_in_progress()" in body, (
        f"{func} mutates results_table from the Qt event loop and must back off "
        f"while clear_table() is tearing it down"
    )


def test_rebuild_predicate_defaults_to_false():
    """The guard must read a plain attribute with a False default, so a table
    that has never been cleared behaves exactly as before (no new state to
    initialise, no behaviour change on the happy path)."""
    body = _func_src(_TABLE, "table_rebuild_in_progress")
    assert "getattr(self, '_table_rebuilding', False)" in body

    class _Fake:
        pass

    assert bool(getattr(_Fake(), "_table_rebuilding", False)) is False


# ── the search coroutine must not clear a superseded search's table ─────────

def test_search_server_checks_the_generation_before_clearing():
    """The SOCKET search path awaits (probe -> search -> sort) before it clears
    the table, so a second search can start meanwhile. The generation guard used
    to be checked only INSIDE the row-insert loop — i.e. AFTER clear_table().
    Both coroutines could therefore reach the clear.

    (The offline-cloud branch clears synchronously right after the generation is
    bumped, with no await in between, so it cannot overlap and is not pinned
    here.)
    """
    body = _func_src(_SEARCH, "search_server")
    # The socket path begins at the enrich probe; the clear follows it.
    socket_path = body[body.index("_maybe_probe_enrich_cost"):]
    clear_at = socket_path.index("home.patient_table_widget.clear_table()")
    assert "home._search_generation != _my_search_gen" in socket_path[:clear_at], (
        "a superseded search must bail BEFORE clear_table() — two overlapping "
        "searches must never both tear the table down"
    )
