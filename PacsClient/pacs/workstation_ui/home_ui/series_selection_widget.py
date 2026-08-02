"""Reusable per-series selection widget (2026-07-30).

Shared by the two export workflows so the UX is identical and there is one
component to maintain:

* Write CD / DVD           (modules/cd_burner/cd_burn_dialog.py — an optional plugin)
* Offline Service / Export (PacsClient/.../offline_cloud_export_dialog.py — core)

It shows a checkable tree — Select-All ▸ per-study ▸ per-series — with the
series description, modality and image count, and returns a
``{study_uid: {series_number, ...}}`` selection map that the CD burn manager and
the offline export engine both understand. Default state is everything checked,
so an untouched dialog exports exactly what it always did.

This lives in the CORE tree (not the run_cd plugin) because the plugin may
import core, but core must never import the plugin.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Roles used to stash identity on tree items.
_ROLE_KIND = Qt.UserRole            # "study" | "series"
_ROLE_STUDY_UID = Qt.UserRole + 1
_ROLE_SERIES_NUMBER = Qt.UserRole + 2


def normalize_series_number(value: Any) -> str:
    """``'02'`` / ``2`` / ``2.0`` → ``'2'`` (matches the export engines)."""
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    try:
        if text.replace(".", "", 1).lstrip("-").isdigit():
            return str(int(float(text)))
    except (TypeError, ValueError):
        pass
    return text


class _SeriesTree(QTreeWidget):
    """QTreeWidget where a click ANYWHERE on a row toggles its checkbox.

    The native check indicator is tiny and hard to hit; here the whole content
    row is a click target, while the expand/collapse triangle (left of column 0)
    still works because we only intercept clicks within the item's content rect.
    """

    def mousePressEvent(self, event):  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and index.column() == 0:
                item = self.itemFromIndex(index)
                if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                    # Only intercept on the CONTENT (right of the branch arrow),
                    # so expand/collapse keeps working.
                    if event.position().toPoint().x() >= self.visualRect(index).left():
                        new = Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked
                        item.setCheckState(0, new)
                        event.accept()
                        return
        super().mousePressEvent(event)


class SeriesSelectionWidget(QWidget):
    """Checkable Select-All ▸ study ▸ series tree.

    Populate with :meth:`set_studies`; read the result with
    :meth:`get_selection` (``None`` when everything is checked → the caller
    should treat that as "all series", i.e. the legacy path).
    """

    selectionChanged = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._updating = False
        self._studies: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.select_all_cb = QCheckBox("Select all series")
        self.select_all_cb.setTristate(True)
        self.select_all_cb.setChecked(True)
        self.select_all_cb.clicked.connect(self._on_select_all_clicked)
        self.select_all_cb.setStyleSheet(
            "QCheckBox { font-size: 14px; font-weight: 600; spacing: 10px; }"
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        header.addWidget(self.select_all_cb)
        header.addStretch(1)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-size: 13px; color: #8ea3ba;")
        header.addWidget(self.summary_label)
        layout.addLayout(header)

        self.tree = _SeriesTree()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Study / Series", "Modality", "Images"])
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(22)
        # Larger, clearly-visible checkboxes + readable rows.
        self.tree.setStyleSheet(
            """
            QTreeWidget { font-size: 13px; }
            QTreeView::item { min-height: 30px; padding: 4px 2px; }
            QTreeView::indicator { width: 20px; height: 20px; }
            """
        )
        self.tree.itemChanged.connect(self._on_item_changed)
        header_view = self.tree.header()
        try:
            header_view.setStretchLastSection(False)
            from PySide6.QtWidgets import QHeaderView

            header_view.setSectionResizeMode(0, QHeaderView.Stretch)
            header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        except Exception:
            pass
        layout.addWidget(self.tree)

    # ------------------------------------------------------------------ build
    def set_studies(self, studies: List[Dict[str, Any]]) -> None:
        """Populate the tree.

        Each study dict: ``study_uid``, ``title`` (or ``patient_name`` +
        ``description``), and ``series`` = list of
        ``{series_number, description, modality, image_count}``. A study with an
        empty ``series`` list is shown as a single always-included row.
        """
        self._studies = studies or []
        self._updating = True
        self.tree.clear()

        for study in self._studies:
            study_uid = str(study.get("study_uid") or "").strip()
            title = self._study_title(study)
            study_item = QTreeWidgetItem([title, "", ""])
            study_item.setData(0, _ROLE_KIND, "study")
            study_item.setData(0, _ROLE_STUDY_UID, study_uid)
            study_item.setFlags(
                (study_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                & ~Qt.ItemIsSelectable
            )
            study_item.setCheckState(0, Qt.Checked)

            series_list = study.get("series") or []
            for series in series_list:
                sn = normalize_series_number(series.get("series_number"))
                desc = str(series.get("description") or series.get("series_description") or "").strip()
                label = f"Series {sn}" if sn else "Series"
                if desc:
                    label = f"{label} — {desc}"
                modality = str(series.get("modality") or "").strip()
                count = series.get("image_count")
                if count is None:
                    count = series.get("number_of_instances") or series.get("images_count")
                count_text = str(count) if count not in (None, "") else ""

                series_item = QTreeWidgetItem([label, modality, count_text])
                series_item.setData(0, _ROLE_KIND, "series")
                series_item.setData(0, _ROLE_STUDY_UID, study_uid)
                series_item.setData(0, _ROLE_SERIES_NUMBER, sn)
                series_item.setFlags(
                    (series_item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsSelectable
                )
                series_item.setCheckState(0, Qt.Checked)
                study_item.addChild(series_item)

            self.tree.addTopLevelItem(study_item)
            study_item.setExpanded(True)

        self._updating = False
        self._refresh_master_and_summary()

    @staticmethod
    def _study_title(study: Dict[str, Any]) -> str:
        explicit = str(study.get("title") or "").strip()
        if explicit:
            return explicit
        bits: List[str] = []
        for key in ("patient_name", "modality", "description", "study_date"):
            val = str(study.get(key) or "").strip()
            if val:
                bits.append(val)
        if bits:
            return "  ·  ".join(bits)
        return str(study.get("study_uid") or "Study")

    # -------------------------------------------------------------- selection
    def get_selection(self) -> Optional[Dict[str, Set[str]]]:
        """``{study_uid: {series_number, ...}}`` of CHECKED series.

        Returns ``None`` when every series of every study is checked, so the
        caller passes ``None`` to the export engines and hits the byte-identical
        legacy path. A study with no enumerable series is always treated as
        fully included and never restricts the map.
        """
        selection: Dict[str, Set[str]] = {}
        everything = True
        for i in range(self.tree.topLevelItemCount()):
            study_item = self.tree.topLevelItem(i)
            study_uid = str(study_item.data(0, _ROLE_STUDY_UID) or "")
            child_count = study_item.childCount()
            if child_count == 0:
                continue  # no series metadata → keep the whole study, no restriction
            chosen: Set[str] = set()
            for j in range(child_count):
                child = study_item.child(j)
                if child.checkState(0) == Qt.Checked:
                    sn = str(child.data(0, _ROLE_SERIES_NUMBER) or "")
                    if sn:
                        chosen.add(sn)
                else:
                    everything = False
            selection[study_uid] = chosen
        if everything:
            return None
        return selection

    def selected_series_count(self) -> int:
        total = 0
        for i in range(self.tree.topLevelItemCount()):
            study_item = self.tree.topLevelItem(i)
            if study_item.childCount() == 0:
                continue
            for j in range(study_item.childCount()):
                if study_item.child(j).checkState(0) == Qt.Checked:
                    total += 1
        return total

    def total_series_count(self) -> int:
        total = 0
        for i in range(self.tree.topLevelItemCount()):
            total += self.tree.topLevelItem(i).childCount()
        return total

    def has_any_selection(self) -> bool:
        """True if at least one series is checked, OR a study has no series rows
        (which means the whole study is included)."""
        for i in range(self.tree.topLevelItemCount()):
            study_item = self.tree.topLevelItem(i)
            if study_item.childCount() == 0:
                return True
            for j in range(study_item.childCount()):
                if study_item.child(j).checkState(0) == Qt.Checked:
                    return True
        return False

    # ----------------------------------------------------------------- events
    def _on_select_all_clicked(self, _checked: bool) -> None:
        # Decide from the ACTUAL current selection, not the tristate click cycle
        # (which would go Unchecked→Partial→Checked and never fully clear):
        # if everything is already selected, clear it; otherwise select all.
        total = self.total_series_count()
        all_selected = total > 0 and self.selected_series_count() == total
        new_state = Qt.Unchecked if all_selected else Qt.Checked
        self.select_all_cb.setCheckState(new_state)
        self._updating = True
        for i in range(self.tree.topLevelItemCount()):
            study_item = self.tree.topLevelItem(i)
            study_item.setCheckState(0, new_state)
            for j in range(study_item.childCount()):
                study_item.child(j).setCheckState(0, new_state)
        self._updating = False
        self._refresh_master_and_summary()
        self.selectionChanged.emit()

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        self._updating = True
        try:
            kind = item.data(0, _ROLE_KIND)
            if kind == "study":
                # Propagate parent → children.
                state = item.checkState(0)
                if state != Qt.PartiallyChecked:
                    for j in range(item.childCount()):
                        item.child(j).setCheckState(0, state)
            elif kind == "series":
                # Reflect children → parent tri-state.
                parent = item.parent()
                if parent is not None:
                    checked = sum(
                        1 for j in range(parent.childCount())
                        if parent.child(j).checkState(0) == Qt.Checked
                    )
                    if checked == 0:
                        parent.setCheckState(0, Qt.Unchecked)
                    elif checked == parent.childCount():
                        parent.setCheckState(0, Qt.Checked)
                    else:
                        parent.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self._updating = False
        self._refresh_master_and_summary()
        self.selectionChanged.emit()

    def _refresh_master_and_summary(self) -> None:
        total = self.total_series_count()
        selected = self.selected_series_count()
        # Master checkbox tri-state.
        self.select_all_cb.blockSignals(True)
        if total == 0 or selected == total:
            self.select_all_cb.setCheckState(Qt.Checked)
        elif selected == 0:
            self.select_all_cb.setCheckState(Qt.Unchecked)
        else:
            self.select_all_cb.setCheckState(Qt.PartiallyChecked)
        self.select_all_cb.blockSignals(False)
        if total:
            self.summary_label.setText(f"{selected} of {total} series selected")
        else:
            self.summary_label.setText("")
