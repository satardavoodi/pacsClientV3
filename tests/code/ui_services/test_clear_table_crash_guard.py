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

These are source-level pins plus behavioural ownership checks against a small
offscreen ``QTableWidget``. They never construct the production home page or
touch the database.
"""
import ast
import pathlib
import textwrap

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


def _load_unbound_method(path: pathlib.Path, name: str):
    namespace = {}
    exec(textwrap.dedent(_func_src(path, name)), namespace)
    return namespace[name]


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
    detach_row = _func_src(_TABLE, "_detach_row_cell_widgets")
    assert "_detach_row_cell_widgets" in detach
    assert "removeCellWidget" in detach_row
    assert "deleteLater()" in detach_row, (
        "cell widgets must be destroyed from the event loop, NOT synchronously "
        "inside setRowCount(0)'s model reset — that is the access-violation window"
    )
    # and the detach must happen BEFORE the model reset (rindex skips the
    # docstring's narrative mention of setRowCount(0))
    assert body.index("self._detach_all_cell_widgets()") < body.rindex("table.setRowCount(0)")


def test_add_patient_data_sets_the_order_item_once():
    """Replacing an owned QTableWidgetItem invalidates its Shiboken wrapper.

    The frozen-build crashes include ``add_patient_data`` at the second write
    to this exact cell, so the row builder must create the item only once.
    """
    body = _func_src(_TABLE, "add_patient_data")
    assert body.count("COL['order']") == 1, (
        "the order cell must not be replaced during initial row construction"
    )


def test_clear_table_takes_items_before_resetting_the_model():
    """Qt-owned item wrappers must leave the table before its model reset."""
    body = _func_src(_TABLE, "clear_table")
    assert "_take_all_table_items" in body
    assert body.index("self._take_all_table_items()") < body.rindex("table.setRowCount(0)")

    helper = _func_src(_TABLE, "_take_all_table_items")
    assert "takeItem" in helper, (
        "takeItem transfers ownership to Python so setRowCount(0) cannot "
        "invalidate every wrapper from inside the Qt model reset"
    )


def test_taken_items_survive_the_real_qt_model_reset():
    """Exercise the production helper against Qt/Shiboken, not a mock."""
    import shiboken6
    from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

    app = QApplication.instance() or QApplication([])

    class _SortableProbe(QTableWidgetItem):
        def __lt__(self, other):
            return self.text() < other.text()

    table = QTableWidget(3, 2)
    original_items = []
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            item = _SortableProbe(f"{row}:{col}")
            table.setItem(row, col, item)
            original_items.append(item)

    assert all(not shiboken6.ownedByPython(item) for item in original_items)

    take_all = _load_unbound_method(_TABLE, "_take_all_table_items")
    owner = type("_Owner", (), {"results_table": table})()
    retired_items = take_all(owner)

    assert len(retired_items) == 6
    assert all(table.item(row, col) is None for row in range(3) for col in range(2))
    assert all(shiboken6.ownedByPython(item) for item in retired_items)
    table.setRowCount(0)
    assert all(shiboken6.isValid(item) for item in retired_items)
    table.deleteLater()
    app.processEvents()


def test_safe_row_removal_takes_items_before_removing_the_row():
    body = _func_src(_TABLE, "_remove_provisional_pin_overlay_row")
    assert "_take_row_items" in body
    assert body.index("_take_row_items") < body.index("removeRow")


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


def test_local_search_does_not_pump_nested_qt_events_after_clear():
    body = _func_src(_SEARCH, "search_local")
    clear_at = body.index("home.patient_table_widget.clear_table()")
    first_await = body.index("await ", clear_at)
    assert "QApplication.processEvents()" not in body[clear_at:first_await], (
        "the coroutine already yields explicitly; pumping Qt events between "
        "clear and that yield can re-enter table producers synchronously"
    )
