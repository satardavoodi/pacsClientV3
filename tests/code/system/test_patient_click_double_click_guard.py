"""Regression guards: patient-list single-click handler must NOT do heavy
selection-model work that breaks Qt double-click detection.

Background - 2026-05-29 user-reported double-click unreliability
================================================================
Users reported that double-clicking a patient row on the Home Page
"often behaves as if only a single click occurred" - the system reloaded
thumbnails (single-click behaviour) instead of opening the patient
(double-click behaviour). Users had to click 3-4 times rapidly before
the viewer tab opened.

Root cause: `_on_patient_clicked` (the itemClicked handler) called
`highlight_selected_row(row)` synchronously on every single click.
That helper does

    self.results_table.clearSelection()
    self.results_table.selectRow(row_index)
    self.results_table.viewport().update()

inside the click handler. clearSelection + selectRow fire
`currentRowChanged` TWICE (once with row=-1, once with row=N), and
`viewport().update()` forces a synchronous repaint. On slower systems
or under UI load that pushed the SECOND mouse press of the user's
double-click past Qt's `doubleClickInterval` (default ~400 ms on
Windows). Qt classified the second press as a fresh single click and
emitted `itemClicked` again instead of `itemDoubleClicked`.

Furthermore, the explicit selection work was REDUNDANT. The table has
`setSelectionBehavior(SelectRows)` + `setSelectionMode(ExtendedSelection)`
which already auto-clears other selections and selects the clicked
row natively in mousePressEvent. The user didn't need us to do it
again.

Fix: skip `highlight_selected_row(row)` in the non-Ctrl branch of
`_on_patient_clicked`. Qt handles selection. The Ctrl branch keeps
`toggle_row_selection(row)` because Ctrl+click is explicitly supposed
to opt out of clear-others.

Guards:
1. `_on_patient_clicked`'s non-Ctrl branch must NOT call
   `highlight_selected_row` (the redundant work that broke
   double-click detection).
2. The table must still wire `itemDoubleClicked` to the open-patient
   handler (so removing the redundant work doesn't break the actual
   double-click path).
3. The table must still wire `itemClicked` to the single-click
   handler (the load-thumbnails path).
4. The table must still have `setSelectionBehavior(SelectRows)` so
   Qt's native selection actually fires on a plain click.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PATIENT_TABLE = (
    REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
    / "patient_table_widget.py"
)


@pytest.fixture(scope="module")
def patient_table_src() -> str:
    return PATIENT_TABLE.read_text(encoding="utf-8")


def _function_body(src: str, def_signature_prefix: str) -> str:
    """Return the lines between `<def_signature_prefix>` and the next
    top-level `def` at the same indentation depth."""
    idx = src.find(def_signature_prefix)
    assert idx >= 0, f"Function {def_signature_prefix!r} not found"
    end = src.find("\n    def ", idx + 1)
    return src[idx : end if end > 0 else len(src)]


def test_single_click_handler_does_not_call_highlight_selected_row(
    patient_table_src: str,
) -> None:
    """`_on_patient_clicked` MUST NOT invoke `highlight_selected_row` -
    that helper's clearSelection + selectRow + viewport().update()
    blocks the event loop long enough to break Qt's double-click
    detection. Qt's ExtendedSelection mode already handles plain-click
    selection natively."""
    body = _function_body(patient_table_src, "    def _on_patient_clicked(self, item):")
    # Look for an actual CALL site (parentheses), not the mention in a
    # comment / docstring. We accept self.highlight_selected_row(...)
    # being mentioned in the docstring but not actually called.
    call_pattern = re.compile(
        r"^\s*self\.highlight_selected_row\s*\(",
        re.MULTILINE,
    )
    matches = call_pattern.findall(body)
    assert not matches, (
        "_on_patient_clicked is calling self.highlight_selected_row(...). "
        "That call's clearSelection+selectRow+viewport().update() blocks "
        "the event loop and breaks Qt's double-click detection. Qt's "
        "ExtendedSelection mode already auto-selects the clicked row "
        "natively. See 2026-05-29 user-reported double-click regression."
    )


def test_item_double_clicked_signal_is_wired(patient_table_src: str) -> None:
    """The patient-open path depends on Qt's itemDoubleClicked signal
    reaching `_on_patient_double_clicked`. If anyone removes this
    connection, double-click stops working entirely."""
    assert (
        "self.results_table.itemDoubleClicked.connect(self._on_patient_double_clicked)"
        in patient_table_src
    ), (
        "results_table.itemDoubleClicked is no longer wired to "
        "_on_patient_double_clicked. Double-clicking a patient row "
        "will not open the viewer tab."
    )


def test_item_clicked_signal_is_wired(patient_table_src: str) -> None:
    """The load-thumbnails path depends on Qt's itemClicked signal
    reaching `_on_patient_clicked`. If this connection is removed,
    single-clicks stop loading thumbnails."""
    assert (
        "self.results_table.itemClicked.connect(self._on_patient_clicked)"
        in patient_table_src
    ), (
        "results_table.itemClicked is no longer wired to "
        "_on_patient_clicked. Single-clicking a patient row will not "
        "load thumbnails."
    )


def test_table_has_select_rows_behavior(patient_table_src: str) -> None:
    """After dropping `highlight_selected_row`, we rely on Qt's native
    selection. That requires `setSelectionBehavior(SelectRows)` - if
    someone changes it to SelectItems or SelectColumns, plain clicks
    would no longer select the whole row and our row-driven
    `currentRowChanged` handler would not fire for clicks on cells
    that host custom widgets."""
    assert (
        "self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)"
        in patient_table_src
    ), (
        "results_table.setSelectionBehavior is no longer SelectRows. "
        "We dropped the explicit highlight_selected_row(row) call in "
        "_on_patient_clicked on the assumption Qt's native row "
        "selection would still fire. If SelectRows is gone, plain "
        "clicks will not select the whole row and the thumbnail-load "
        "path breaks."
    )
