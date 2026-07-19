"""Benchmark: sorting the patient table by the widget-backed Status/Report columns.

Measures the REAL cost — a live QTableWidget whose Status and Report cells hold
actual QWidgets (as they do in production), sorted through the same
``sortItems`` path the header click uses.

Run offscreen:
    .venv\\Scripts\\python.exe tools\\dev\\bench_status_report_sort.py

The clinic list is typically a few hundred rows; 2000+ is well past anything
the UI shows. Anything under ~100 ms is imperceptible; 16 ms is one frame.
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QWidget,
)

from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import (  # noqa: E402
    SortableItem,
    report_status_rank,
    status_flags_rank,
)

STATUSES = [
    "pending",
    "awaiting_physician_approval",
    "awaiting_secretary_approval",
    "physician_approved",
    "secretary_approved",
    "completed",
    "archived",
]

FLAG_SETS = [
    {},
    {"dicom": True},
    {"dicom": True, "voice": True},
    {"voice": True, "ai": True},
    {"dicom": True, "voice": True, "ai": True, "printed": True},
]


def build_table(n_rows: int) -> QTableWidget:
    """A table shaped like the real one: widgets in the two sortable columns."""
    table = QTableWidget()
    table.setColumnCount(4)  # date, time, status, report
    table.setRowCount(n_rows)
    for row in range(n_rows):
        # Heavy tie density: only 40 distinct dates, so the tie-break path —
        # the expensive one — runs for most comparisons.
        date_key = 20260718 - (row % 40)
        time_key = (row * 37) % 86400
        table.setItem(row, 0, SortableItem(str(date_key), sort_key=date_key))
        table.setItem(row, 1, SortableItem(str(time_key), sort_key=time_key))

        flags = FLAG_SETS[row % len(FLAG_SETS)]
        status_widget = QWidget()
        layout = QHBoxLayout(status_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("chip"))
        status_widget.status_flags = flags
        status_widget.status_rank = status_flags_rank(flags)

        report_status = STATUSES[row % len(STATUSES)]
        report_widget = QWidget()
        rlayout = QHBoxLayout(report_widget)
        rlayout.setContentsMargins(0, 0, 0, 0)
        rlayout.addWidget(QLabel(report_status))
        report_widget.report_status = report_status

        table.setItem(row, 2, SortableItem("", sort_key=status_widget.status_rank,
                                           tiebreak=(date_key, time_key)))
        table.setItem(row, 3, SortableItem("", sort_key=report_status_rank(report_status),
                                           tiebreak=(date_key, time_key)))
        table.setCellWidget(row, 2, status_widget)
        table.setCellWidget(row, 3, report_widget)
    return table


def refresh_keys(table: QTableWidget) -> None:
    """Mirror of _refresh_widget_sort_keys — the pre-sort re-sync pass."""
    for row in range(table.rowCount()):
        d = table.item(row, 0)
        t = table.item(row, 1)
        tiebreak = (getattr(d, "_sort_key", 0) or 0, getattr(t, "_sort_key", 0) or 0)
        it = table.item(row, 2)
        if it is not None:
            w = table.cellWidget(row, 2)
            rank = getattr(w, "status_rank", None)
            if rank is None:
                rank = status_flags_rank(getattr(w, "status_flags", None))
            it._sort_key = int(rank)
            it._tiebreak = tiebreak
        it = table.item(row, 3)
        if it is not None:
            w = table.cellWidget(row, 3)
            it._sort_key = report_status_rank(getattr(w, "report_status", None))
            it._tiebreak = tiebreak


def bench(n_rows: int) -> None:
    table = build_table(n_rows)

    t0 = time.perf_counter()
    refresh_keys(table)
    refresh_ms = (time.perf_counter() - t0) * 1000

    timings = {}
    for label, col, order in (
        ("Report desc", 3, Qt.DescendingOrder),
        ("Report asc", 3, Qt.AscendingOrder),
        ("Status desc", 2, Qt.DescendingOrder),
    ):
        table.setSortingEnabled(True)
        SortableItem._descending = order == Qt.DescendingOrder
        t0 = time.perf_counter()
        table.sortItems(col, order)
        elapsed = (time.perf_counter() - t0) * 1000
        SortableItem._descending = False
        table.setSortingEnabled(False)
        timings[label] = elapsed

    worst = max(timings.values())
    total = refresh_ms + worst
    verdict = "OK" if total < 100 else ("SLOW" if total < 300 else "FAIL")
    print(
        f"{n_rows:>6} rows | key refresh {refresh_ms:7.1f} ms | "
        + " | ".join(f"{k} {v:7.1f} ms" for k, v in timings.items())
        + f" | worst click {total:7.1f} ms  [{verdict}]"
    )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    print("Sorting the widget-backed Status/Report columns (offscreen Qt)")
    print("A header click costs: key refresh + one sort. 16 ms = one frame.\n")
    for n in (100, 500, 1000, 2000, 5000):
        bench(n)
    print("\nNote: the key refresh does no DB/disk work — it reads attributes")
    print("already stashed on the cell widgets.")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
