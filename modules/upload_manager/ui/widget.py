"""UploadManagerWidget — a module tab that mirrors the Download Manager UX for
External Consultation uploads (ADR-0009 D2/D3/D4).

A live QTableWidget (same column vocabulary as Download Manager) + the same
control set (Pause/Resume/Cancel/Retry/Remove). Reuses the existing transfer
engine via the UploadManager singleton; never performs transfers itself and
never imports modules.download_manager.

Optimized for stability (ADR-0009 hardening):
  * Refreshes ONLY when the tab is visible AND the store actually changed
    (a dirty-flag set by a thread-safe store observer) — idle cost is ~nil.
  * Updates rows IN PLACE (no setRowCount churn / full clears every tick) so the
    table never flickers and the user's selection is preserved; a full
    structural rebuild happens only when the set/order of jobs changes.
  * The observer only flips an atomic bool (it can fire from the worker thread);
    all Qt widget work happens on the GUI thread inside the timer tick.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.enums import UploadStatus
from ..manager import get_upload_manager
from ..state.store import get_state_store

logger = logging.getLogger(__name__)

_COLS = [
    "Patient", "Patient ID", "Study Date", "Modality", "Consultant",
    "Target Folder", "Status", "Progress", "Speed", "ETA", "Verify",
]
_PROGRESS_COL = 7
_REFRESH_MS = 350


def _fmt_eta(sec):
    if sec is None or sec <= 0:
        return "—"
    sec = int(sec)
    return f"{sec // 60}m {sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def _fmt_speed(bps):
    if not bps or bps <= 0:
        return "—"
    mb = bps / (1024.0 * 1024.0)
    return f"{mb:.1f} MB/s" if mb >= 1 else f"{bps / 1024.0:.0f} KB/s"


def _verify_text(st) -> str:
    if st.status != UploadStatus.COMPLETED:
        return ""
    bits = ["DICOM ✓" if st.dicom_upload_ok else "DICOM …",
            "Meta ✓" if st.metadata_registered else "Meta …"]
    if st.assigned_consultant:
        bits.append("Assigned ✓" if st.consultant_assigned else "Assigned …")
    return "  ".join(bits)


def _text_cells(st):
    """The 10 non-progress column strings for a state (index-aligned to _COLS)."""
    return {
        0: st.patient_name or "—", 1: st.patient_id or "—", 2: st.study_date or "—",
        3: st.modality or "—", 4: st.assigned_consultant or "—",
        5: (st.target_folder or st.consultation_id or "—"), 6: st.status.value,
        8: _fmt_speed(st.speed_bps), 9: _fmt_eta(st.eta_seconds), 10: _verify_text(st),
    }


class UploadManagerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UploadManagerWidget")
        self._mgr = get_upload_manager()
        self._store = get_state_store()
        self._row_jobs: list[str] = []     # row index -> job_id
        self._last_job_ids: tuple = ()      # structural signature
        self._dirty = True
        self._build()
        # Thread-safe: the observer only flips a bool (may run on a worker thread).
        self._observer = lambda *_a: self._mark_dirty()
        self._store.add_observer(self._observer)
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── lifecycle ──
    def _mark_dirty(self):
        self._dirty = True

    def showEvent(self, e):
        self._dirty = True
        self._tick()
        super().showEvent(e)

    def closeEvent(self, e):
        try:
            self._store.remove_observer(self._observer)
        except Exception:
            pass
        super().closeEvent(e)

    # ── UI ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        bar = QHBoxLayout()
        title = QLabel("Consultation Uploads")
        title.setStyleSheet("font-size:15px;font-weight:600;")
        bar.addWidget(title)
        bar.addStretch(1)
        self._btn_pause = QPushButton("Pause")
        self._btn_resume = QPushButton("Resume")
        self._btn_cancel = QPushButton("Cancel")
        self._btn_retry = QPushButton("Retry")
        self._btn_remove = QPushButton("Remove completed")
        for b, fn in (
            (self._btn_pause, self._on_pause), (self._btn_resume, self._on_resume),
            (self._btn_cancel, self._on_cancel), (self._btn_retry, self._on_retry),
            (self._btn_remove, self._on_remove_completed),
        ):
            b.clicked.connect(fn)
            bar.addWidget(b)
        root.addLayout(bar)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        root.addWidget(self._table, 1)
        self._empty = QLabel("No uploads yet. Send an External consultation to queue one here.")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet("color:#888;")
        root.addWidget(self._empty)

    # ── live refresh (visible + dirty only) ──
    def _tick(self):
        if not self.isVisible() or not self._dirty:
            return
        self._dirty = False
        try:
            states = sorted(self._store.all(), key=lambda s: (s.is_terminal, -int(s.priority)))
            self._empty.setVisible(not states)
            sig = tuple(s.job_id for s in states)
            if sig != self._last_job_ids:
                self._rebuild(states)        # structural change only
                self._last_job_ids = sig
            else:
                self._update_in_place(states)  # cheap, no flicker, keeps selection
        except Exception as exc:  # a refresh must never crash the tab
            logger.debug("upload manager refresh skipped: %s", exc)

    def _rebuild(self, states):
        self._row_jobs = [s.job_id for s in states]
        self._table.setRowCount(len(states))
        for r, st in enumerate(states):
            for c, v in _text_cells(st).items():
                self._table.setItem(r, c, QTableWidgetItem(str(v)))
            bar = QProgressBar()
            bar.setRange(0, 100)
            self._table.setCellWidget(r, _PROGRESS_COL, bar)
            self._apply_progress(bar, st)

    def _update_in_place(self, states):
        for r, st in enumerate(states):
            for c, v in _text_cells(st).items():
                it = self._table.item(r, c)
                if it is None:
                    self._table.setItem(r, c, QTableWidgetItem(str(v)))
                elif it.text() != str(v):
                    it.setText(str(v))
            bar = self._table.cellWidget(r, _PROGRESS_COL)
            if isinstance(bar, QProgressBar):
                self._apply_progress(bar, st)

    @staticmethod
    def _apply_progress(bar, st):
        val = int(st.percent)
        if bar.value() != val:
            bar.setValue(val)
        bar.setFormat(f"{val}%  {st.uploaded_files}/{st.total_files}")

    def _selected_job(self):
        sm = self._table.selectionModel()
        rows = sm.selectedRows() if sm else []
        if not rows:
            return None
        idx = rows[0].row()
        return self._row_jobs[idx] if 0 <= idx < len(self._row_jobs) else None

    # ── controls (delegate to the manager; mark dirty for instant feedback) ──
    def _on_pause(self):
        jid = self._selected_job()
        if jid:
            self._mgr.pause(jid); self._mark_dirty()

    def _on_resume(self):
        jid = self._selected_job()
        if jid:
            self._mgr.resume(jid); self._mark_dirty()

    def _on_cancel(self):
        jid = self._selected_job()
        if jid:
            self._mgr.cancel(jid); self._mark_dirty()

    def _on_retry(self):
        jid = self._selected_job()
        if jid:
            self._mgr.retry(jid); self._mark_dirty()

    def _on_remove_completed(self):
        self._mgr.remove_completed(); self._mark_dirty(); self._tick()
