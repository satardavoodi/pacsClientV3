"""Guards for sortable Status / Report columns (2026-07-18).

Both columns render a CELL WIDGET, and a widget carries no item data — which
is precisely why Qt could not sort them and they were the only two unsortable
columns. They are now backed by a hidden ``SortableItem`` carrying:

    sort_key = rank (report workflow stage / status indicator weight)
    tiebreak = the row's (date, time), always newest-first

PERFORMANCE IS PART OF THE CONTRACT, not a nice-to-have: the sort must not
query the database, walk the disk, or recompute the expensive local-status
flags. The benchmark at the bottom fails loudly if that regresses.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (  # noqa: E402
    COL,
    REPORT_STATUS_RANK,
    STATUS_FLAG_WEIGHTS,
    SortableItem,
    report_status_rank,
    status_flags_rank,
)


def _src() -> str:
    root = Path(__file__).resolve().parents[3]
    rel = "PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py"
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def _method_code(name: str) -> str:
    """Return a method's body with docstrings and comments stripped.

    These files are heavily commented, and the comments legitimately discuss
    the very calls the tests forbid ("...rather than calling ``setItem``").
    Scanning raw text therefore matches the prose and fails a correct
    implementation, so strip anything that is not code first.
    """
    body = _src().split(f"def {name}", 1)[1].split("\n    def ", 1)[0]
    # drop the docstring
    if '"""' in body:
        parts = body.split('"""')
        body = "".join(parts[2:]) if len(parts) >= 3 else body
    # drop full-line and trailing comments
    lines = []
    for line in body.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The columns are actually enabled for sorting
# ---------------------------------------------------------------------------


def test_status_and_report_are_registered_sortable():
    src = _src()
    block = src.split("self._tri_sortable_cols = {", 1)[1].split("}", 1)[0]
    assert "COL['status']" in block
    assert "COL['report']" in block
    assert "COL['imported_on']" in block


def test_hidden_sort_items_are_created_for_the_widget_cells():
    src = _src()
    assert "_apply_status_sort_key" in src
    assert "_apply_report_sort_key" in src
    # ...and are set right where the widgets are installed
    setcell = src.split("setCellWidget(row, COL['report'], report_container)", 1)[1][:400]
    assert "_apply_status_sort_key" in setcell
    assert "_apply_report_sort_key" in setcell


def test_sortable_headers_have_base_titles():
    """Without a base title the ▲/▼ suffix is never stripped and accumulates."""
    src = _src()
    block = src.split("self._header_titles = {", 1)[1].split("}", 1)[0]
    for name in ("status", "report", "imported_on"):
        assert f"COL['{name}']" in block


# ---------------------------------------------------------------------------
# Report ranking — "reported studies appear first" on the first click
# ---------------------------------------------------------------------------


def test_report_rank_orders_by_workflow_completeness():
    assert report_status_rank("completed") > report_status_rank("secretary_approved")
    assert report_status_rank("secretary_approved") > report_status_rank("physician_approved")
    assert report_status_rank("physician_approved") > report_status_rank("awaiting_secretary_approval")
    assert report_status_rank("awaiting_secretary_approval") > report_status_rank("awaiting_physician_approval")
    assert report_status_rank("awaiting_physician_approval") > report_status_rank("awaiting_approval")
    assert report_status_rank("awaiting_approval") > report_status_rank("pending")
    assert report_status_rank("pending") > report_status_rank("archived")


def test_first_click_is_descending_so_completed_lands_on_top():
    """The header cycle is default -> DESCENDING -> ascending, so a HIGHER rank
    must mean 'more complete' for the user's stated expectation to hold."""
    src = _src()
    assert "new_state, order = 2, Qt.DescendingOrder" in src
    ranks = [report_status_rank(s) for s in ("pending", "physician_approved", "completed")]
    assert ranks == sorted(ranks), "rank must increase with completeness"


def test_every_known_report_status_has_a_rank():
    from modules.network.socket_report_status_service import REPORT_STATUSES

    for status in REPORT_STATUSES:
        assert status in REPORT_STATUS_RANK, f"{status} has no sort rank"


def test_unknown_and_legacy_report_values_are_handled():
    assert report_status_rank("complete") == report_status_rank("completed")
    assert report_status_rank("") == report_status_rank("pending")
    assert report_status_rank(None) == report_status_rank("pending")
    assert report_status_rank("  COMPLETED  ") == report_status_rank("completed")


# ---------------------------------------------------------------------------
# Status ranking — DICOM dominates
# ---------------------------------------------------------------------------


def test_dicom_outranks_every_combination_without_it():
    """A row holding local images must sort above one that holds only lesser
    indicators, no matter how many of them it has."""
    everything_but_dicom = {k: True for k in STATUS_FLAG_WEIGHTS if k != "dicom"}
    assert status_flags_rank({"dicom": True}) > status_flags_rank(everything_but_dicom)


def test_more_indicators_rank_higher_within_the_same_class():
    assert status_flags_rank({"dicom": True, "voice": True}) > status_flags_rank({"dicom": True})
    assert status_flags_rank({"voice": True}) > status_flags_rank({"ai": True})


def test_empty_status_ranks_zero():
    assert status_flags_rank({}) == 0
    assert status_flags_rank(None) == 0
    assert status_flags_rank({"dicom": False, "voice": False}) == 0


# ---------------------------------------------------------------------------
# Tie-break behaviour
# ---------------------------------------------------------------------------


def test_ties_break_by_datetime_newest_first():
    older = SortableItem("", sort_key=7, tiebreak=(20200101, 900))
    newer = SortableItem("", sort_key=7, tiebreak=(20260718, 1430))
    SortableItem._descending = False
    try:
        # newest-first means the newer item compares as "less than" (sorts earlier)
        assert newer < older
        assert not (older < newer)
    finally:
        SortableItem._descending = False


def test_tiebreak_stays_newest_first_when_the_primary_is_reversed():
    """Qt reverses the comparator for descending; the tie-break compensates so
    ties do not silently flip to oldest-first."""
    older = SortableItem("", sort_key=7, tiebreak=(20200101, 900))
    newer = SortableItem("", sort_key=7, tiebreak=(20260718, 1430))
    SortableItem._descending = True
    try:
        # Qt will invert this result, so __lt__ must return the inverse for the
        # on-screen order to stay newest-first.
        assert older < newer
    finally:
        SortableItem._descending = False


def test_primary_still_wins_over_the_tiebreak():
    completed_old = SortableItem("", sort_key=7, tiebreak=(20200101, 0))
    pending_new = SortableItem("", sort_key=1, tiebreak=(20260718, 0))
    SortableItem._descending = False
    try:
        assert pending_new < completed_old  # rank 1 < rank 7
    finally:
        SortableItem._descending = False


def test_sort_direction_flag_is_always_reset():
    """A leaked flag would corrupt the NEXT sort's tie-breaks."""
    block = _method_code("_programmatic_sort")
    assert "SortableItem._descending = (order == Qt.DescendingOrder)" in block
    assert "finally:" in block
    assert "SortableItem._descending = False" in block
    # the reset must come after the sort call, inside the finally
    assert block.index("sortItems") < block.rindex("SortableItem._descending = False")


def test_mixed_key_types_do_not_raise():
    a = SortableItem("a", sort_key=5)
    b = SortableItem("b", sort_key="x")
    a < b  # must not raise
    b < a


# ---------------------------------------------------------------------------
# Performance contract
# ---------------------------------------------------------------------------


def test_refresh_does_no_database_or_disk_work():
    """The sort path must not query the DB or recompute the expensive flags."""
    body = _method_code("_refresh_widget_sort_keys")
    for forbidden in (
        "_compute_local_status_flags",
        "get_db_connection",
        "os.walk",
        "os.path.exists",
        "_is_study_downloaded",
        "dcmread",
    ):
        assert forbidden not in body, f"{forbidden} must not run during a sort"


def test_refresh_mutates_in_place_rather_than_resetting_items():
    """setItem would emit dataChanged for every row and force a repaint."""
    body = _method_code("_refresh_widget_sort_keys")
    assert "_sort_key =" in body and "_tiebreak =" in body
    assert "setItem" not in body, "must mutate the existing items, not replace them"


def test_refresh_runs_only_for_the_widget_backed_columns():
    block = _method_code("_programmatic_sort")
    assert "if col in (COL['status'], COL['report']):" in block


def test_hidden_sort_item_stays_selectable():
    """REGRESSION (reported 2026-07-18): the hidden sort items were created
    with bare ``Qt.ItemIsEnabled``, which strips ItemIsSelectable. Those two
    cells then did not join the row's selection, so clicking a row highlighted
    every column EXCEPT Status and Report — a dark "shadow" gap punched
    through the selection band.

    Verified empirically: a cell with NO item (the pre-change state) IS
    selected, so the flags must keep ItemIsSelectable to match.
    """
    body = _method_code("_make_hidden_sort_item")
    assert "Qt.ItemIsEnabled)" not in body, (
        "bare ItemIsEnabled strips ItemIsSelectable and breaks the row highlight"
    )
    assert "item.flags() & ~Qt.ItemIsEditable" in body, (
        "use the same flags as every other cell (_mk): default minus editable"
    )


def test_hidden_sort_item_flags_match_normal_cells():
    """The behavioural half of the guard above, on real Qt items."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QTableWidgetItem

    reference = QTableWidgetItem("")           # what _mk starts from
    reference.setFlags(reference.flags() & ~_Qt.ItemIsEditable)

    hidden = SortableItem("", sort_key=0, tiebreak=(0, 0))
    hidden.setFlags(hidden.flags() & ~_Qt.ItemIsEditable)

    assert bool(hidden.flags() & _Qt.ItemIsSelectable), "must join the row selection"
    assert bool(hidden.flags() & _Qt.ItemIsEnabled)
    assert not bool(hidden.flags() & _Qt.ItemIsEditable)
    assert hidden.flags() == reference.flags()


def test_dicom_weight_exceeds_the_sum_of_all_others():
    """Pins the arithmetic the dominance rule depends on, so adding a new flag
    without raising the DICOM weight fails here rather than in the field."""
    others = sum(w for k, w in STATUS_FLAG_WEIGHTS.items() if k != "dicom")
    assert STATUS_FLAG_WEIGHTS["dicom"] > others


@pytest.mark.parametrize("n_rows", [500, 5000])
def test_sort_comparison_cost_scales(n_rows):
    """Benchmark the actual comparison work on a large list.

    This measures the Python-side ``__lt__`` cost that dominates a
    ``QTableWidget.sortItems`` call. A realistic clinic page is a few hundred
    rows; 5000 is well past anything the list shows.
    """
    items = []
    for i in range(n_rows):
        items.append(
            SortableItem(
                "",
                sort_key=i % 8,                      # 8 report ranks
                tiebreak=(20260718 - (i % 400), i),  # heavy tie density
            )
        )

    SortableItem._descending = False
    try:
        start = time.perf_counter()
        items.sort()
        elapsed = time.perf_counter() - start
    finally:
        SortableItem._descending = False

    # Generous ceiling: the point is to catch an accidental O(n^2) or a
    # per-comparison DB/disk hit, not to police microseconds.
    budget = 0.5 if n_rows <= 500 else 3.0
    assert elapsed < budget, (
        f"sorting {n_rows} rows took {elapsed:.3f}s (budget {budget}s) — "
        f"something expensive crept into the comparison path"
    )


def test_ranking_helpers_are_pure_and_cheap():
    """They run once per row on build/refresh; keep them allocation-light."""
    flags = {"dicom": True, "voice": True, "ai": True}
    start = time.perf_counter()
    for _ in range(100_000):
        status_flags_rank(flags)
        report_status_rank("completed")
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"ranking helpers too slow: {elapsed:.3f}s for 100k calls"


def test_status_flags_are_stashed_on_the_widget_to_avoid_recompute():
    src = _src()
    build = src.split("def _build_local_status_widget", 1)[1][:1500]
    assert "container.status_flags" in build
    assert "container.status_rank" in build
