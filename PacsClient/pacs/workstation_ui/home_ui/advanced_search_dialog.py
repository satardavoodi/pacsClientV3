"""Advanced patient search dialog (2026-06-06).

Opened from the funnel icon inside the Patient ID field on the home page.
Builds a STRUCTURED, versioned query dict that
HomeSearchService.search_server_advanced executes:

  - multiple Patient IDs (paste a list — comma / space / newline separated)
  - date range (preset or custom from/to)
  - modalities
  - body part, age range, reporting physician (server returns the rows;
    these refine client-side when the row carries the field)

The query dict is deliberately flat and versioned so future fields
(reception/admission filters, study description, etc.) extend it without
breaking the executor.
"""
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDialog, QDateEdit, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

try:
    from PacsClient.utils.custom_checkbox import CustomCheckbox
except Exception:  # pragma: no cover — fallback for isolated tests
    from PySide6.QtWidgets import QCheckBox as CustomCheckbox

try:
    from PacsClient.utils.theme_manager import get_theme_manager
except Exception:  # pragma: no cover
    get_theme_manager = None

_MODALITIES = ['DX', 'CT', 'MR', 'US', 'MG', 'CR', 'NM', 'PT', 'XA']

QUERY_VERSION = 1


def parse_patient_ids(raw_text: str) -> list:
    """Split a pasted blob of IDs on commas / semicolons / whitespace.

    '1,2 3\\n4;5' -> ['1','2','3','4','5'] (order kept, duplicates removed).
    """
    out = []
    seen = set()
    for token in str(raw_text or '').replace(',', ' ').replace(';', ' ').split():
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


class AdvancedSearchDialog(QDialog):
    """Structured multi-field search popup. Call get_query() after exec()."""

    _DATE_PRESETS = [
        ("Any date", None),
        ("Today", 0),
        ("Yesterday", 1),
        ("Last week", 7),
        ("Last month", 30),
        ("Last 3 months", 90),
        ("Last year", 365),
        ("Custom range", "custom"),
    ]

    # Import date = when the study FIRST entered THIS local database
    # (studies.imported_at), NOT the acquisition/study date. Local-only filter.
    _IMPORT_PRESETS = [
        ("Any import date", None),
        ("Imported today", 0),
        ("Imported yesterday", 1),
        ("Imported two days ago", 2),
        ("Custom import date", "single"),
        ("Import date range", "range"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Patient Search")
        self.setModal(True)
        self.setMinimumWidth(430)
        self._theme = {}
        if get_theme_manager is not None:
            try:
                self._theme = get_theme_manager().current_theme() or {}
            except Exception:
                self._theme = {}
        self._build_ui()
        self._apply_style()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Patient IDs (multi)
        ids_group = QGroupBox("Patient IDs — one or many (comma / space / new line)")
        ids_layout = QVBoxLayout(ids_group)
        self.ids_edit = QPlainTextEdit()
        self.ids_edit.setPlaceholderText("e.g. 44820 44534 44113\nor paste a list of up to 20 IDs")
        self.ids_edit.setFixedHeight(64)
        ids_layout.addWidget(self.ids_edit)
        root.addWidget(ids_group)

        # Date range
        date_group = QGroupBox("Date range")
        date_layout = QGridLayout(date_group)
        self.date_preset = QComboBox()
        for label, data in self._DATE_PRESETS:
            self.date_preset.addItem(label, data)
        self.date_preset.currentIndexChanged.connect(self._on_date_preset_changed)
        date_layout.addWidget(self.date_preset, 0, 0, 1, 2)

        self.date_from = QDateEdit()
        self.date_to = QDateEdit()
        for de in (self.date_from, self.date_to):
            de.setDisplayFormat("yyyy-MM-dd")
            de.setCalendarPopup(True)
            de.setDate(QDate.currentDate())
            de.setEnabled(False)
            try:
                cal = de.calendarWidget()
                if cal is not None:
                    cal.setFirstDayOfWeek(Qt.DayOfWeek.Saturday)
            except Exception:
                pass
        date_layout.addWidget(QLabel("From"), 1, 0)
        date_layout.addWidget(self.date_from, 1, 1)
        date_layout.addWidget(QLabel("To"), 2, 0)
        date_layout.addWidget(self.date_to, 2, 1)
        root.addWidget(date_group)

        # Import date (LOCAL only) — when the study first entered this database
        imp_group = QGroupBox("Import date (local — when imported to this computer)")
        imp_layout = QGridLayout(imp_group)
        self.import_preset = QComboBox()
        for label, data in self._IMPORT_PRESETS:
            self.import_preset.addItem(label, data)
        self.import_preset.currentIndexChanged.connect(self._on_import_preset_changed)
        imp_layout.addWidget(self.import_preset, 0, 0, 1, 2)

        self.import_from = QDateEdit()
        self.import_to = QDateEdit()
        for de in (self.import_from, self.import_to):
            de.setDisplayFormat("yyyy-MM-dd")
            de.setCalendarPopup(True)
            de.setDate(QDate.currentDate())
            de.setEnabled(False)
            try:
                cal = de.calendarWidget()
                if cal is not None:
                    cal.setFirstDayOfWeek(Qt.DayOfWeek.Saturday)
            except Exception:
                pass
        self.import_from_label = QLabel("From")
        self.import_to_label = QLabel("To")
        imp_layout.addWidget(self.import_from_label, 1, 0)
        imp_layout.addWidget(self.import_from, 1, 1)
        imp_layout.addWidget(self.import_to_label, 2, 0)
        imp_layout.addWidget(self.import_to, 2, 1)
        root.addWidget(imp_group)

        # Modalities
        mod_group = QGroupBox("Modalities (none checked = all)")
        mod_layout = QGridLayout(mod_group)
        self.modality_checks = {}
        for idx, modality in enumerate(_MODALITIES):
            check = CustomCheckbox(modality)
            self.modality_checks[modality] = check
            mod_layout.addWidget(check, idx // 3, idx % 3)
        root.addWidget(mod_group)

        # Clinical refinements
        ref_group = QGroupBox("Clinical filters")
        ref_layout = QGridLayout(ref_group)
        self.body_part_edit = QLineEdit()
        self.body_part_edit.setPlaceholderText("Body part (e.g. CHEST, KNEE)")
        ref_layout.addWidget(QLabel("Body part"), 0, 0)
        ref_layout.addWidget(self.body_part_edit, 0, 1, 1, 3)

        self.age_min = QSpinBox()
        self.age_min.setRange(0, 150)
        self.age_min.setSpecialValueText("Any")
        self.age_max = QSpinBox()
        self.age_max.setRange(0, 150)
        self.age_max.setSpecialValueText("Any")
        ref_layout.addWidget(QLabel("Age from"), 1, 0)
        ref_layout.addWidget(self.age_min, 1, 1)
        ref_layout.addWidget(QLabel("to"), 1, 2)
        ref_layout.addWidget(self.age_max, 1, 3)

        self.physician_edit = QLineEdit()
        self.physician_edit.setPlaceholderText("Reporting doctor / radiologist (e.g. Alizadeh)")
        ref_layout.addWidget(QLabel("Physician"), 2, 0)
        ref_layout.addWidget(self.physician_edit, 2, 1, 1, 3)
        root.addWidget(ref_group)

        note = QLabel(
            "Patient IDs, dates and modalities filter on the server. Body part, "
            "age and physician refine the returned results when that data is available."
        )
        note.setWordWrap(True)
        note.setObjectName("AdvNote")
        root.addWidget(note)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.search_btn = QPushButton("Search")
        self.search_btn.setDefault(True)
        self.search_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.search_btn)
        root.addLayout(btn_row)

    def _on_date_preset_changed(self, _index):
        data = self.date_preset.currentData()
        custom = data == "custom"
        self.date_from.setEnabled(custom)
        self.date_to.setEnabled(custom)
        if isinstance(data, int):
            today = QDate.currentDate()
            self.date_from.setDate(today.addDays(-int(data)))
            self.date_to.setDate(today)

    def _on_import_preset_changed(self, _index):
        data = self.import_preset.currentData()
        single = data == "single"          # one custom import date
        rng = data == "range"              # from/to import date range
        self.import_from.setEnabled(single or rng)
        self.import_to.setEnabled(rng)
        # In single-date mode the "To" picker is hidden (from == to).
        self.import_to.setVisible(not single)
        self.import_to_label.setVisible(not single)
        self.import_from_label.setText("Date" if single else "From")
        if isinstance(data, int):
            # preset day offset (0=today, 1=yesterday, 2=two days ago)
            day = QDate.currentDate().addDays(-int(data))
            self.import_from.setDate(day)
            self.import_to.setDate(day)

    def _apply_style(self):
        t = self._theme

        def tok(key, fallback):
            return t.get(key, fallback) if isinstance(t, dict) else fallback

        self.setStyleSheet(f"""
            QDialog {{ background: {tok('panel_bg', '#111827')}; }}
            QGroupBox {{
                color: {tok('text_primary', '#f7fafc')};
                border: 1px solid {tok('border', '#374151')};
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 10px;
                font-size: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: {tok('text_muted', '#9ca3af')};
            }}
            QLabel {{ color: {tok('text_primary', '#e5e7eb')}; font-size: 12px; }}
            QLabel#AdvNote {{ color: {tok('text_muted', '#9ca3af')}; font-size: 11px; }}
            QPlainTextEdit, QLineEdit, QDateEdit, QComboBox, QSpinBox {{
                background: {tok('panel_alt_bg', '#0f1419')};
                color: {tok('text_primary', '#f7fafc')};
                border: 1px solid {tok('border', '#374151')};
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QPushButton {{
                background: {tok('panel_alt_bg', '#1f2937')};
                color: {tok('text_primary', '#f7fafc')};
                border: 1px solid {tok('border', '#374151')};
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {tok('accent', '#3b82f6')}; }}
            QPushButton:default {{
                background: {tok('accent', '#2563eb')};
                color: {tok('button_text', '#ffffff')};
                border-color: {tok('accent', '#2563eb')};
            }}
        """)

    # ── Query ───────────────────────────────────────────────────────────

    def get_query(self) -> dict:
        """Structured, versioned advanced query for HomeSearchService."""
        data = self.date_preset.currentData()
        date_from = date_to = None
        if data == "custom":
            date_from = self.date_from.date().toString("yyyyMMdd")
            date_to = self.date_to.date().toString("yyyyMMdd")
        elif isinstance(data, int):
            today = QDate.currentDate()
            date_from = today.addDays(-int(data)).toString("yyyyMMdd")
            date_to = today.toString("yyyyMMdd")

        modalities = [m for m, c in self.modality_checks.items() if c.isChecked()]

        # Import-date range (LOCAL, studies.imported_at) as 'yyyy-MM-dd' or None.
        import_from = import_to = None
        idata = self.import_preset.currentData()
        if idata == "single":
            import_from = import_to = self.import_from.date().toString("yyyy-MM-dd")
        elif idata == "range":
            import_from = self.import_from.date().toString("yyyy-MM-dd")
            import_to = self.import_to.date().toString("yyyy-MM-dd")
        elif isinstance(idata, int):
            day = QDate.currentDate().addDays(-int(idata))
            import_from = import_to = day.toString("yyyy-MM-dd")

        return {
            'version': QUERY_VERSION,
            'patient_ids': parse_patient_ids(self.ids_edit.toPlainText()),
            'date_from': date_from,
            'date_to': date_to,
            'modalities': modalities,
            'body_part': self.body_part_edit.text().strip(),
            'age_min': self.age_min.value() if self.age_min.value() > 0 else None,
            'age_max': self.age_max.value() if self.age_max.value() > 0 else None,
            'physician': self.physician_edit.text().strip(),
            'import_date_from': import_from,
            'import_date_to': import_to,
        }
