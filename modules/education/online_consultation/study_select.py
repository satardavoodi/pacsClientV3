"""Select local studies for a consultation and stage them as an Offline Cloud package.

Two layers:

* :func:`build_export_callable` — **Qt-free**. Returns the ``export_callable(dest)``
  the compose dialog expects: it stages the selected studies into ``dest`` using the
  EXISTING, unchanged offline engine (``export_studies_to_offline_cloud``) and
  returns the package root. Raises ``RuntimeError`` on any export error so a broken
  package can never be uploaded silently.
* :class:`ConsultationStudySelectDialog` — a small multi-select picker over the
  local database (same query shape as the education ``StudyPickerDialog``), returning
  ``{label, study_uids, export_callable}`` for ``ConsultationComposeDialog``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_export_callable(study_uids: list[str], actor: dict | None = None):
    """Return ``export_callable(dest) -> package_root`` for the given study UIDs.

    The callable runs the existing offline export engine against a staging folder
    (the consultation upload directory). BLOCKING — the compose dialog already runs
    it on a worker thread.
    """
    uids = [str(u or "").strip() for u in (study_uids or []) if str(u or "").strip()]

    def _export(dest: str):
        if not uids:
            raise RuntimeError("No studies selected for the consultation.")
        from PacsClient.utils.offline_cloud import export_studies_to_offline_cloud

        result = export_studies_to_offline_cloud(
            {"folder_path": str(dest), "name": "online-consultation"},
            uids,
            actor=actor or {},
            operation="consultation_export",
        )
        if not result.get("ok"):
            errors = "; ".join(str(e) for e in result.get("errors") or []) or "unknown error"
            raise RuntimeError(f"Package export failed: {errors}")
        exported = int(result.get("exported") or 0)
        if exported < len(uids):
            logger.warning(
                "consultation export: %d/%d studies exported (%s)",
                exported, len(uids), result.get("errors"),
            )
        return str(dest)

    return _export


def build_selection(rows: list[dict], actor: dict | None = None) -> dict:
    """Build the compose-dialog ``selection`` dict from picked study rows.

    ``rows`` items need ``study_uid`` and optionally ``patient_name`` /
    ``study_description``. Qt-free (unit-testable headless).
    """
    uids = [r.get("study_uid", "") for r in rows if r.get("study_uid")]
    names = sorted({str(r.get("patient_name") or "").strip() for r in rows if r.get("patient_name")})
    label = ", ".join(names[:3]) + ("…" if len(names) > 3 else "") if names else "Selected studies"
    titles = [str(r.get("study_description") or "").strip() for r in rows]
    default_title = next((t for t in titles if t), "")
    return {
        "label": f"{label} — {len(uids)} study(ies)",
        "study_uids": uids,
        "default_title": default_title,
        "export_callable": build_export_callable(uids, actor=actor),
    }


class ConsultationStudySelectDialog:
    """Factory wrapper so importing this module stays Qt-free.

    Use :meth:`create` to build the actual QDialog (imports PySide6 lazily).
    """

    def __new__(cls, *args, **kwargs):  # pragma: no cover - thin Qt factory
        return cls.create(*args, **kwargs)

    @staticmethod
    def create(parent=None, actor: dict | None = None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QDialog,
            QHBoxLayout,
            QHeaderView,
            QLabel,
            QLineEdit,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
        )

        from modules.cloud_consultation.ui._theme import palette

        class _Dialog(QDialog):
            def __init__(self):
                super().__init__(parent)
                self._actor = actor or {}
                self.selection: dict | None = None
                self._p = palette()
                self.setWindowTitle("Select studies for consultation")
                self.setMinimumSize(940, 540)
                self._build()
                self._load()

            def _build(self):
                p = self._p
                root = QVBoxLayout(self)
                root.setContentsMargins(16, 16, 16, 16)
                root.setSpacing(10)

                title = QLabel("Select one or more studies to send for consultation")
                title.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
                root.addWidget(title)

                self.search = QLineEdit()
                self.search.setPlaceholderText("Filter by patient name / ID / description…")
                self.search.textChanged.connect(self._apply_filter)
                root.addWidget(self.search)

                self.table = QTableWidget(0, 6)
                self.table.setHorizontalHeaderLabels(
                    ["Patient ID", "Patient name", "Date", "Description", "Modality", "Study UID"]
                )
                self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
                self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
                self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
                self.table.verticalHeader().setVisible(False)
                header = self.table.horizontalHeader()
                header.setSectionResizeMode(QHeaderView.Stretch)
                header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
                header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
                header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
                self.table.itemSelectionChanged.connect(self._update_count)
                root.addWidget(self.table, 1)

                bottom = QHBoxLayout()
                self.count_label = QLabel("0 studies selected")
                self.count_label.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
                bottom.addWidget(self.count_label, 1)
                cancel = QPushButton("Cancel")
                cancel.clicked.connect(self.reject)
                ok = QPushButton("Use selected studies")
                ok.setObjectName("primary")
                ok.clicked.connect(self._accept_selection)
                bottom.addWidget(cancel)
                bottom.addWidget(ok)
                root.addLayout(bottom)

                self.setStyleSheet(
                    f"""
                    QDialog {{ background:{p['surface']}; }}
                    QLineEdit {{ background:{p['surface2']}; color:{p['text']};
                        border:1px solid {p['border']}; border-radius:8px; padding:7px 10px; }}
                    QTableWidget {{ background:{p['surface2']}; color:{p['text']};
                        border:1px solid {p['border']}; border-radius:8px;
                        gridline-color:{p['border']}; }}
                    QHeaderView::section {{ background:{p['surface']}; color:{p['text_muted']};
                        border:none; border-bottom:1px solid {p['border']}; padding:6px; }}
                    QPushButton {{ background:transparent; color:{p['text_muted']};
                        border:1px solid {p['border']}; border-radius:8px;
                        padding:8px 16px; font-size:13px; }}
                    QPushButton#primary {{ background:{p['accent']};
                        color:{p['button_text']}; border:none; }}
                    """
                )

            def _load(self):
                try:
                    import sqlite3

                    from PacsClient.utils.database import get_db_connection

                    with get_db_connection() as conn:
                        conn.row_factory = sqlite3.Row
                        cur = conn.cursor()
                        cur.execute(
                            """
                            SELECT p.patient_id, p.patient_name, s.study_date,
                                   s.study_description, s.modality, s.study_uid
                            FROM studies s
                            JOIN patients p ON s.patient_fk = p.patient_pk
                            WHERE s.study_uid IS NOT NULL AND s.study_uid != ''
                            ORDER BY s.study_date DESC
                            LIMIT 1000
                            """
                        )
                        rows = cur.fetchall()
                except Exception as exc:
                    logger.warning("loading studies for consultation picker failed: %s", exc)
                    rows = []

                self.table.setRowCount(len(rows))
                for i, r in enumerate(rows):
                    vals = [
                        r["patient_id"] or "", r["patient_name"] or "",
                        r["study_date"] or "", r["study_description"] or "",
                        r["modality"] or "", r["study_uid"] or "",
                    ]
                    for c, v in enumerate(vals):
                        item = QTableWidgetItem(str(v))
                        if c == 5:
                            item.setData(Qt.UserRole, r["study_uid"])
                        self.table.setItem(i, c, item)

            def _apply_filter(self, text: str):
                needle = (text or "").strip().lower()
                for i in range(self.table.rowCount()):
                    hay = " ".join(
                        (self.table.item(i, c).text() if self.table.item(i, c) else "")
                        for c in (0, 1, 3)
                    ).lower()
                    self.table.setRowHidden(i, bool(needle) and needle not in hay)

            def _picked_rows(self) -> list[dict]:
                rows = []
                for idx in sorted({i.row() for i in self.table.selectedIndexes()}):
                    if self.table.isRowHidden(idx):
                        continue
                    rows.append({
                        "patient_id": self.table.item(idx, 0).text(),
                        "patient_name": self.table.item(idx, 1).text(),
                        "study_description": self.table.item(idx, 3).text(),
                        "study_uid": self.table.item(idx, 5).text(),
                    })
                return rows

            def _update_count(self):
                self.count_label.setText(f"{len(self._picked_rows())} studies selected")

            def _accept_selection(self):
                rows = self._picked_rows()
                if not rows:
                    self.count_label.setText("Select at least one study.")
                    return
                self.selection = build_selection(rows, actor=self._actor)
                self.accept()

        return _Dialog()
