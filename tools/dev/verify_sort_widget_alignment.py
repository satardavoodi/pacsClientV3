"""Verify that CELL WIDGETS stay aligned with their row's data after a sort.

This is a CORRECTNESS / SAFETY check, not a benchmark.

``_programmatic_sort`` already carries a warning that per-row checkbox
cell-widgets "do not travel reliably" with ``sortItems``. The Status and Report
columns are widget-backed, so if widgets did NOT follow their rows, sorting
would leave a patient row displaying ANOTHER patient's report status — which
would be far worse than the columns simply not being sortable.

This script proves the alignment holds by stamping each row with a unique id in
both the item data and the widget, sorting, and checking every row still
matches.

Run offscreen:
    .venv\\Scripts\\python.exe tools\\dev\\verify_sort_widget_alignment.py
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QTableWidget, QWidget  # noqa: E402

from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (  # noqa: E402
    SortableItem,
    report_status_rank,
)

STATUSES = ["pending", "completed", "archived", "physician_approved",
            "awaiting_secretary_approval", "secretary_approved"]


def run(n_rows: int, col: int, order, label: str) -> bool:
    table = QTableWidget()
    table.setColumnCount(3)  # uid, status-ish, report
    table.setRowCount(n_rows)

    for row in range(n_rows):
        uid = f"UID-{row:05d}"
        status = STATUSES[row % len(STATUSES)]
        date_key = 20260718 - (row % 30)

        uid_item = SortableItem(uid, sort_key=row)
        table.setItem(row, 0, uid_item)

        report_item = SortableItem("", sort_key=report_status_rank(status),
                                   tiebreak=(date_key, row))
        table.setItem(row, 2, report_item)

        # The widget carries the SAME identity as the row's item data. After a
        # sort they must still agree.
        widget = QWidget()
        lbl = QLabel(status, widget)
        widget.report_status = status
        widget.owner_uid = uid
        table.setCellWidget(row, 2, widget)

    table.setSortingEnabled(True)
    SortableItem._descending = order == Qt.DescendingOrder
    table.sortItems(col, order)
    SortableItem._descending = False
    table.setSortingEnabled(False)

    mismatches = 0
    rank_violations = 0
    prev_rank = None
    for row in range(n_rows):
        uid = table.item(row, 0).text()
        widget = table.cellWidget(row, 2)
        item = table.item(row, 2)
        if widget is None:
            mismatches += 1
            continue
        # 1. widget travelled with its row
        if getattr(widget, "owner_uid", None) != uid:
            mismatches += 1
            continue
        # 2. the hidden sort item still describes the widget it sits behind
        if item is not None and item._sort_key != report_status_rank(widget.report_status):
            mismatches += 1
            continue
        # 3. the resulting order actually honours the rank
        rank = item._sort_key if item is not None else 0
        if prev_rank is not None:
            if order == Qt.DescendingOrder and rank > prev_rank:
                rank_violations += 1
            if order == Qt.AscendingOrder and rank < prev_rank:
                rank_violations += 1
        prev_rank = rank

    ok = mismatches == 0 and rank_violations == 0
    print(f"  {label:<28} rows={n_rows:<6} "
          f"widget/data mismatches={mismatches:<4} order violations={rank_violations:<4} "
          f"[{'PASS' if ok else 'FAIL'}]")
    return ok


def check_tiebreak_direction(n_rows: int = 400) -> bool:
    """Within one rank, rows must be newest-first in BOTH directions."""
    results = {}
    for order, name in ((Qt.DescendingOrder, "desc"), (Qt.AscendingOrder, "asc")):
        table = QTableWidget()
        table.setColumnCount(1)
        table.setRowCount(n_rows)
        for row in range(n_rows):
            # one single rank so EVERY comparison exercises the tie-break
            date_key = 20260101 + (row % 50)
            table.setItem(row, 0, SortableItem(str(date_key), sort_key=5,
                                               tiebreak=(date_key, 0)))
        table.setSortingEnabled(True)
        SortableItem._descending = order == Qt.DescendingOrder
        table.sortItems(0, order)
        SortableItem._descending = False
        table.setSortingEnabled(False)
        seq = [table.item(r, 0)._tiebreak[0] for r in range(n_rows)]
        results[name] = seq == sorted(seq, reverse=True)
        print(f"  tie-break newest-first ({name:<4})           "
              f"[{'PASS' if results[name] else 'FAIL'}]")
    return all(results.values())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    print("Cell-widget alignment after sort (offscreen Qt)\n")

    ok = True
    for n in (50, 500, 2000):
        ok &= run(n, 2, Qt.DescendingOrder, "Report descending")
        ok &= run(n, 2, Qt.AscendingOrder, "Report ascending")
    print()
    ok &= check_tiebreak_direction()

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    del app
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
