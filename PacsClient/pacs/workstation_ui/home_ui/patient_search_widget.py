from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QGroupBox, QLineEdit, QPushButton, QLabel, QDateEdit, \
    QHBoxLayout, QComboBox, QCheckBox, QSizePolicy
from PySide6.QtCore import Signal, QDate, Qt
import qtawesome as qta
import os
from datetime import datetime, timedelta
from PacsClient.utils.custom_checkbox import CustomCheckbox
from PacsClient.utils.theme_manager import get_theme_manager

class PatientSearchWidget(QWidget):
    """
    Patient Search Component - Extracted from HomePanelWidget
    Provides search functionality for patient and study information
    """

    # Signal emitted when search button is clicked
    searchRequested = Signal()
    # Signal emitted when cancel search button is clicked
    cancelSearchRequested = Signal()
    # Structured advanced query from the Patient-ID filter popup (2026-06-06)
    advancedSearchRequested = Signal(dict)

    def __init__(self, parent=None):
        super(PatientSearchWidget, self).__init__(parent)
        self._is_searching = False
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()
        self.setup_ui()
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)

    def setup_ui(self):
        """Setup the Patient Search UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(0)

        # Create search group
        search_group = QGroupBox("Patient Search")
        self.search_group = search_group
        search_group.setStyleSheet("""
            QGroupBox {
                font-size: 14pt;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                border: 1px solid #4a5568;
                border-radius: 8px;
                margin: 4px 0px;
                padding-top: 10px;
                background: #0f1419;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background: #0f1419;
                border-radius: 5px;
                color: #f7fafc;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                font-size: 13pt;
            }
        """)

        # Layout اصلی گروه جستجو
        self.search_layout = QVBoxLayout()
        self.search_layout.setContentsMargins(10, 10, 10, 10)
        self.search_layout.setSpacing(6)

        # Modality box
        self._create_modalites_box()
        self.search_layout.addWidget(self.modality_group)

        # حالا فیلدها را به صورت ستونی اضافه می‌کنیم (label بالای field)
        self._create_search_fields()  # فیلدها را ایجاد می‌کند

        self._add_fields_to_layout()  # متد جدید برای اضافه کردن ستونی

        search_group.setLayout(self.search_layout)
        main_layout.addWidget(search_group, stretch=1)  # stretch=1 برای پر کردن ارتفاع

        # Create search button and cancel button layout
        self._create_search_button()
        # Create a wrapper widget for the button layout
        self.search_buttons_widget = QWidget()
        self.search_buttons_widget.setLayout(self.search_button_layout)
        self.search_buttons_widget.setStyleSheet("background: transparent;")
        main_layout.addWidget(self.search_buttons_widget)

        self._apply_field_styling()
        self._apply_date_field_styling()

        # تنظیم SizePolicy برای کل ویجت
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def _create_modalites_box(self):
        """Create modality checkboxes group"""
        self.modality_group = QGroupBox()
        self.modality_group.setStyleSheet("""
            QGroupBox {
                font-size: 14pt;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                border: 0px solid #4a5568;
                margin: 4px 0px;
                padding-top: 8px;
                background: #0f1419;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px 0 8px;
                background: #0f1419;
                border-radius: 5px;
                color: #f7fafc;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                font-size: 13pt;
            }
        """)

        self._modality_layout = QGridLayout()
        self._modality_layout.setContentsMargins(5, 5, 5, 5)
        self._modality_layout.setSpacing(3)
        self._modality_layout.setColumnStretch(0, 1)
        self._modality_layout.setColumnStretch(1, 1)
        self._modality_layout.setColumnStretch(2, 1)

        self.modality_checks = {}
        self._populate_modality_checks(self._load_configured_modalities())

        self.modality_group.setLayout(self._modality_layout)

    # Fallback when the Viewer Configuration modality grid is unavailable.
    _DEFAULT_FILTER_MODALITIES = ['DX', 'CT', 'MR', 'US', 'MG', 'CR', 'NM', 'PT', 'XA']

    def _load_configured_modalities(self):
        """Modality filter options come from the Viewer Configuration
        modality grid (config/modality_grid.json) — Settings ↔ Home filter
        reconnect, 2026-06-06. Falls back to the classic list when the
        config is missing/unreadable."""
        try:
            import json as _json
            from pathlib import Path as _Path
            from PacsClient.utils.config import SOCKET_CONFIG_PATH
            cfg_path = _Path(SOCKET_CONFIG_PATH) / 'modality_grid.json'
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = _json.load(f)
            layouts = cfg.get('modality_layouts') if isinstance(cfg, dict) else None
            if not isinstance(layouts, dict):
                layouts = cfg if isinstance(cfg, dict) else {}
            names = []
            for raw in layouts.keys():
                name = str(raw or '').strip().upper()
                if name and name != 'DEFAULT' and name not in names:
                    names.append(name)
            if names:
                return names
        except Exception:
            pass
        return list(self._DEFAULT_FILTER_MODALITIES)

    def _populate_modality_checks(self, modalities, previously_checked=None):
        previously_checked = previously_checked or set()
        cols = 3
        for idx, modality in enumerate(modalities):
            check = CustomCheckbox(modality)
            check.setToolTip(f"💡 Include {modality} imaging studies in search")
            check.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            if modality in previously_checked:
                check.setChecked(True)
            self.modality_checks[modality] = check
            self._modality_layout.addWidget(check, idx // cols, idx % cols)

    def reload_modalities(self):
        """Rebuild the modality filter checkboxes from the saved Viewer
        Configuration (called after Settings 'Save Changes'). Added
        modalities appear, removed ones disappear; check states of the
        surviving modalities are preserved."""
        try:
            previously_checked = {
                m for m, c in self.modality_checks.items() if c.isChecked()
            }
            while self._modality_layout.count():
                item = self._modality_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self.modality_checks = {}
            self._populate_modality_checks(
                self._load_configured_modalities(), previously_checked
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "reload_modalities failed", exc_info=True
            )

    def _add_fields_to_layout(self):
        """Add all fields to the search layout in column format (label above field)"""
        self._add_widget_to_search_layout('Patient ID', self.patient_id_edit)
        self._add_widget_to_search_layout('Patient Name', self.patient_name_edit)
        self._add_widget_to_search_layout('Date Range', self.date_selector)
        self._add_widget_to_search_layout('Date From', self.date_from_edit)
        self._add_widget_to_search_layout('Date To', self.date_to_edit)

        # Spacer برای پر کردن فضای باقی‌مانده
        self.search_layout.addStretch(1)

    def _add_widget_to_search_layout(self, name: str, widget):
        """Add widget to vertical layout without label (using placeholder instead)"""
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.search_layout.addWidget(widget)

    def _create_search_button(self):
        """Create the search button and cancel button"""
        # Button layout to hold both search and cancel buttons
        self.search_button_layout = QHBoxLayout()
        self.search_button_layout.setSpacing(6)
        self.search_button_layout.setContentsMargins(0, 6, 0, 6)

        # Search button
        self.search_btn = QPushButton(qta.icon('fa5s.search', color='white'), " Search Patients")
        self.search_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                color: #ffffff;
                border: 1px solid #059669;
                border-radius: 7px;
                padding: 8px 14px;
                font-size: 13pt;
                font-family: 'Roboto', sans-serif;
                margin: 0px;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #047857, stop:1 #065f46);
                border-color: #047857;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #065f46, stop:1 #064e3b);
            }
        """)
        # V2 parallel design (opt-in, default OFF): render Search as the single
        # accent "primary" action. No-op unless ui_variant('home')=='v2'; any
        # failure leaves the V1 green style above untouched.
        try:
            from PacsClient.utils.v2_style import apply_search_button_v2
            apply_search_button_v2(self.search_btn)
        except Exception:
            pass
        self.search_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_btn.clicked.connect(self._on_search_clicked)
        self.search_button_layout.addWidget(self.search_btn)

        # Cancel search button (hidden by default)
        self.cancel_search_btn = QPushButton(qta.icon('fa5s.stop-circle', color='white'), " Cancel Search")
        self.cancel_search_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);
                color: #ffffff;
                border: 1px solid #dc2626;
                border-radius: 7px;
                padding: 8px 14px;
                font-size: 13pt;
                font-family: 'Roboto', sans-serif;
                margin: 0px;
                letter-spacing: 0.5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #b91c1c, stop:1 #991b1b);
                border-color: #b91c1c;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #991b1b, stop:1 #7f1d1d);
            }
        """)
        self.cancel_search_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cancel_search_btn.setVisible(False)
        self.cancel_search_btn.clicked.connect(self._on_cancel_search_clicked)
        self.search_button_layout.addWidget(self.cancel_search_btn)

    def _on_cancel_search_clicked(self):
        """Handle cancel search button click"""
        self.cancelSearchRequested.emit()

    def set_searching_state(self, is_searching: bool):
        """Toggle between search and cancel button visibility"""
        self._is_searching = is_searching
        self.search_btn.setVisible(not is_searching)
        self.cancel_search_btn.setVisible(is_searching)

    def _create_search_fields(self):
        """Create all search input fields"""
        # Patient Information Fields
        self.patient_id_edit = QLineEdit()
        self.patient_id_edit.setPlaceholderText("Patient ID (e.g., 12345)")
        self.patient_id_edit.setToolTip("💡 Patient's unique identifier\nExample: 12345, P001, etc.")
        self.patient_id_edit.setMaxLength(50)
        # Pressing Enter in the Patient ID field triggers the search,
        # exactly like clicking the Search Patients button.
        self.patient_id_edit.returnPressed.connect(self._on_search_clicked)

        # Advanced filter popup trigger (2026-06-06): a small filter icon
        # INSIDE the Patient ID field (trailing position — same visual
        # language as the date-range dropdown button). Opens the structured
        # multi-ID / date / modality / clinical filter dialog.
        try:
            self._advanced_filter_action = self.patient_id_edit.addAction(
                qta.icon('fa5s.sliders-h', color='#9ca3af'),
                QLineEdit.ActionPosition.TrailingPosition,
            )
            self._advanced_filter_action.setToolTip(
                "Advanced search…\nMultiple patient IDs, date range, modality, "
                "body part, age, reporting doctor"
            )
            self._advanced_filter_action.triggered.connect(self._open_advanced_search_dialog)
        except Exception:
            self._advanced_filter_action = None

        self.patient_name_edit = QLineEdit()
        self.patient_name_edit.setPlaceholderText("Patient Name (e.g., John Doe)")
        self.patient_name_edit.setToolTip(
            "💡 Patient's full name\nSupports partial matching\nExample: John, Doe, John Doe")
        self.patient_name_edit.setMaxLength(100)

        self.patient_sex = QLineEdit()
        self.patient_sex.setPlaceholderText("Gender (M/F/O)")
        self.patient_sex.setToolTip("💡 Patient's gender\nM = Male\nF = Female\nO = Other")
        self.patient_sex.setMaxLength(1)

        # Study Information Fields
        self.study_id = QLineEdit()
        self.study_id.setPlaceholderText("Study ID (e.g., S001)")
        self.study_id.setToolTip("💡 Unique study identifier\nAssigned by the system\nExample: S001, ST123")
        self.study_id.setMaxLength(50)

        # Date selector combo box
        self.date_selector = QComboBox()
        self.date_selector.addItem("Custom Date", "custom")
        self.date_selector.addItem("All Dates", "all_dates")
        self.date_selector.addItem("Today", "today")
        self.date_selector.addItem("Yesterday", "yesterday")
        self.date_selector.addItem("Two days ago", "two_days_ago")
        self.date_selector.addItem("Last Week", "last_week")
        self.date_selector.addItem("Last Month", "last_month")
        self.date_selector.addItem("Last Year", "last_year")
        self.date_selector.setToolTip("💡 Quick date selection options")
        self.date_selector.currentTextChanged.connect(self._on_date_selector_changed)
        # Preset RE-click fix (2026-06-06): currentTextChanged does NOT fire
        # when the user re-picks the already-selected preset, so "Yesterday"
        # could not reset manually-edited date fields without first switching
        # to another preset. `activated` fires on EVERY user selection —
        # including the same item — and re-applies the preset dates.
        # (Double apply on a *changed* selection is idempotent.)
        self.date_selector.activated.connect(self._on_date_selector_activated)

        # Date From field
        self.date_from_edit = QDateEdit()
        self.date_from_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_from_edit.setToolTip("💡 Start date for date range search\nClick to select date")
        self.date_from_edit.setCalendarPopup(True)
        self.date_from_edit.setDate(QDate.currentDate())

        # Date To field
        self.date_to_edit = QDateEdit()
        self.date_to_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_to_edit.setToolTip("💡 End date for date range search\nClick to select date")
        self.date_to_edit.setCalendarPopup(True)
        self.date_to_edit.setDate(QDate.currentDate())

        self.study_description = QLineEdit()
        self.study_description.setPlaceholderText("Study Description (e.g., Chest CT)")
        self.study_description.setToolTip(
            "💡 Description of the medical examination\nExample: Chest CT, Brain MRI, Abdominal US")
        self.study_description.setMaxLength(200)

        self.series_description = QLineEdit()
        self.series_description.setPlaceholderText("Series Description (e.g., Axial)")
        self.series_description.setToolTip("💡 Description of the imaging series\nExample: Axial, Coronal, Sagittal")
        self.series_description.setMaxLength(200)

        # Modality field
        self.modality = QComboBox()
        self.modality.addItem("All Modalities", "")
        self.modality.addItem("CT", "CT")
        self.modality.addItem("MR", "MR")
        self.modality.addItem("US", "US")
        self.modality.addItem("CR", "CR")
        self.modality.addItem("DX", "DX")
        self.modality.addItem("MG", "MG")
        self.modality.addItem("NM", "NM")
        self.modality.addItem("PT", "PT")
        self.modality.addItem("RF", "RF")
        self.modality.addItem("SC", "SC")
        self.modality.addItem("XA", "XA")
        self.modality.setToolTip("💡 Medical imaging modality type")

        # Request Type field
        self.request_type = QComboBox()
        self.request_type.addItem("All Types", "")
        self.request_type.addItem("Study Query", "STUDY")
        self.request_type.addItem("Patient Query", "PATIENT")
        self.request_type.addItem("Series Query", "SERIES")
        self.request_type.setToolTip("💡 Type of DICOM query to perform")

        # Apply consistent styling
        self._apply_field_styling()
        self._apply_date_field_styling()

    def _apply_field_styling(self, theme=None):
        """Apply consistent styling to all input fields with scalable font in pt"""
        t = theme or self._active_theme
        base_pt = 13
        combo_pt = 12
        date_pt = 12

        fields = [
            self.patient_id_edit,
            self.patient_name_edit,
            self.patient_sex,
            self.study_id,
            self.date_selector,
            self.date_from_edit,
            self.date_to_edit,
            self.study_description,
            self.series_description,
            self.modality,
            self.request_type
        ]

        for field in fields:
            if isinstance(field, QComboBox):
                field.setStyleSheet(f"""
                    QComboBox {{
                        background: {t['panel_alt_bg']};
                        border: 1px solid {t['border']};
                        border-radius: 5px;
                        padding: 6px 10px;
                        font-size: {combo_pt}pt;
                        font-family: 'Roboto', sans-serif;
                        color: {t['text_primary']};
                        selection-background-color: {t['accent']};
                    }}
                    QComboBox:hover {{
                        border: 1px solid {t['accent']};
                        background: {t['card_bg']};
                    }}
                    QComboBox:focus {{
                        border: 2px solid {t['accent']};
                        background: {t['card_bg']};
                        outline: none;
                    }}
                    QComboBox::drop-down {{
                        border: none;
                        width: 30px;
                        background: {t['card_bg']};
                        border-left: 1px solid {t['border']};
                        border-top-right-radius: 5px;
                        border-bottom-right-radius: 5px;
                        subcontrol-origin: padding;
                        subcontrol-position: right center;
                    }}
                    QComboBox::down-arrow {{
                        width: 0;
                        height: 0;
                        border-left: 5px solid transparent;
                        border-right: 5px solid transparent;
                        border-top: 6px solid {t['text_muted']};
                    }}
                    QComboBox::down-arrow:hover {{
                        border-top-color: {t['text_primary']};
                    }}
                    QComboBox QAbstractItemView {{
                        background: {t['panel_bg']};
                        border: 1px solid {t['border']};
                        border-radius: 5px;
                        color: {t['text_primary']};
                        selection-background-color: {t['accent']};
                        selection-color: {t['button_text']};
                        outline: none;
                        font-size: {combo_pt}pt;
                    }}
                    QComboBox QAbstractItemView::item {{
                        padding: 6px 10px;
                        border: none;
                    }}
                    QComboBox QAbstractItemView::item:hover {{
                        background: {t['card_bg']};
                    }}
                    QComboBox QAbstractItemView::item:selected {{
                        background: {t['accent']};
                        color: {t['button_text']};
                    }}
                """)
            elif isinstance(field, QDateEdit):
                field.setStyleSheet(f"""
                    QDateEdit {{
                        background: {t['panel_alt_bg']};
                        border: 1px solid {t['border']};
                        border-radius: 5px;
                        padding: 6px 10px;
                        font-size: {date_pt}pt;
                        font-family: 'Roboto', sans-serif;
                        color: {t['text_primary']};
                        selection-background-color: {t['accent']};
                    }}
                    QDateEdit:hover {{
                        border: 1px solid {t['accent']};
                        background: {t['card_bg']};
                    }}
                    QDateEdit:focus {{
                        border: 2px solid {t['accent']};
                        background: {t['card_bg']};
                        outline: none;
                    }}
                    QDateEdit::drop-down {{
                        border: none;
                        width: 30px;
                        background: {t['card_bg']};
                        border-left: 1px solid {t['border']};
                        border-top-right-radius: 5px;
                        border-bottom-right-radius: 5px;
                        subcontrol-origin: padding;
                        subcontrol-position: right center;
                    }}
                    QDateEdit::down-arrow {{
                        width: 0;
                        height: 0;
                        border-left: 5px solid transparent;
                        border-right: 5px solid transparent;
                        border-top: 6px solid {t['text_muted']};
                    }}
                    QDateEdit::down-arrow:hover {{
                        border-top-color: {t['text_primary']};
                    }}
                    QCalendarWidget {{
                        background-color: {t['panel_bg']};
                    }}
                    QCalendarWidget QWidget {{
                        color: {t['text_primary']};
                    }}
                    QCalendarWidget QAbstractItemView:enabled {{
                        background-color: {t['card_bg']};
                        color: {t['text_primary']};
                        selection-background-color: {t['accent']};
                        selection-color: {t['button_text']};
                    }}
                    QCalendarWidget QToolButton {{
                        color: {t['text_primary']};
                        background-color: {t['card_bg']};
                        border-radius: 4px;
                        padding: 4px;
                    }}
                    QCalendarWidget QToolButton:hover {{
                        background-color: {t['menu_hover_bg']};
                    }}
                    QCalendarWidget QSpinBox {{
                        background-color: {t['card_bg']};
                        color: {t['text_primary']};
                        border: 1px solid {t['border']};
                    }}
                    QCalendarWidget QMenu {{
                        background-color: {t['panel_bg']};
                        color: {t['text_primary']};
                    }}
                """)
                field.setCalendarPopup(True)
            else:
                field.setStyleSheet(f"""
                    QLineEdit {{
                        background: {t['panel_alt_bg']};
                        border: 1px solid {t['border']};
                        border-radius: 5px;
                        padding: 6px 10px;
                        font-size: {base_pt}pt;
                        font-family: 'Roboto', sans-serif;
                        color: {t['text_primary']};
                        selection-background-color: {t['accent']};
                    }}
                    QLineEdit:hover {{
                        border: 1px solid {t['accent']};
                        background: {t['card_bg']};
                    }}
                    QLineEdit:focus {{
                        border: 2px solid {t['accent']};
                        background: {t['card_bg']};
                        outline: none;
                    }}
                    QLineEdit::placeholder {{
                        color: {t['text_muted']};
                        font-style: italic;
                    }}
                """)

    def _apply_date_field_styling(self, theme=None):
        """Safer/lighter styling for date fields (QDateEdit + popup calendar)"""
        from PySide6.QtGui import QFont, QFontMetrics
        from PySide6.QtWidgets import QCalendarWidget

        t = theme or self._active_theme
        date_fields = [self.date_from_edit, self.date_to_edit]

        date_pt = 12
        calendar_pt = 11
        pad_y, pad_x = 5, 8

        for field in date_fields:
            if not field:
                continue

            field.setCalendarPopup(True)
            f = QFont(field.font())
            f.setPointSize(date_pt)
            field.setFont(f)
            fm = QFontMetrics(f)
            min_h = max(22, int(fm.height() * 1.4))
            # Calendar button visibility (2026-06-06): the drop-down zone was
            # styled border-less/transparent with NO ::down-arrow rule, which
            # rendered it invisible — users had no clue the fields open a
            # calendar. Style it like the "Today" (date-range) combo's button:
            # a bordered zone with a triangle arrow.
            field.setStyleSheet(f"""
                QDateEdit {{
                    background: {t['panel_alt_bg']};
                    border: 1px solid {t['border']};
                    border-radius: 5px;
                    padding: {pad_y}px {pad_x}px;
                    font-size: {date_pt}pt;
                    color: {t['text_primary']};
                    selection-background-color: {t['accent']};
                }}
                QDateEdit:hover {{ border: 1px solid {t['accent']}; background: {t['card_bg']}; }}
                QDateEdit:focus {{ border: 2px solid {t['accent']}; background: {t['card_bg']}; }}
                QDateEdit::drop-down {{
                    border: none;
                    width: 30px;  /* EXACTLY the date-range combo's button width
                                     so all three dropdown icons align vertically */
                    background: {t['card_bg']};
                    border-left: 1px solid {t['border']};
                    border-top-right-radius: 5px;
                    border-bottom-right-radius: 5px;
                    subcontrol-origin: padding;
                    subcontrol-position: right center;
                }}
                QDateEdit::down-arrow {{
                    width: 0;
                    height: 0;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid {t['text_muted']};
                }}
                QDateEdit::down-arrow:hover {{
                    border-top-color: {t['text_primary']};
                }}
            """)
            field.setMinimumHeight(min_h + pad_y * 2)

            cal = field.calendarWidget()
            if cal is None:
                cal = QCalendarWidget()
                field.setCalendarWidget(cal)

            # Month view opens with a weekday header; the working week here
            # starts on Saturday (Sat/Sun/Mon...), so order the columns that way.
            try:
                cal.setFirstDayOfWeek(Qt.DayOfWeek.Saturday)
                cal.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
                cal.setGridVisible(True)
            except Exception:
                pass

            cal_f = QFont(cal.font())
            cal_f.setPointSize(calendar_pt)
            cal.setFont(cal_f)
            cfm = cal.fontMetrics()
            cell_h = max(18, int(cfm.height() * 1.3))
            nav_h = max(22, int(cfm.height() * 1.5))

            cal.setStyleSheet(f"""
                QCalendarWidget {{
                    background: {t['panel_bg']};
                    border: 1px solid {t['accent']};
                    border-radius: 6px;
                }}
                QCalendarWidget QWidget#qt_calendar_navigationbar {{
                    background: {t['card_bg']};
                    border-bottom: 1px solid {t['border']};
                    min-height: {nav_h}px;
                }}
                QCalendarWidget QToolButton {{
                    color: {t['text_primary']};
                    background: transparent;
                    font-size: {calendar_pt}pt;
                    padding: 2px 5px;
                }}
                QCalendarWidget QToolButton:hover {{ background: {t['menu_hover_bg']}; }}
                QCalendarWidget QAbstractItemView {{
                    selection-background-color: {t['accent']};
                    selection-color: {t['button_text']};
                    outline: none;
                    font-size: {calendar_pt}pt;
                    color: {t['text_primary']};
                    background: {t['panel_bg']};
                    gridline-color: {t['border']};
                }}
                QCalendarWidget QAbstractItemView:item {{
                    min-height: {cell_h}px;
                    margin: 1px;
                    border-radius: 3px;
                }}
                QCalendarWidget QAbstractItemView:item:hover {{ background: {t['card_bg']}; }}
                QCalendarWidget QTableView QHeaderView::section {{
                    background: {t['card_bg']};
                    color: {t['text_secondary']};
                    font-size: {calendar_pt}pt;
                    padding: 2px 0px;
                    border: none;
                }}
            """)

    def apply_theme(self, theme=None):
        self._active_theme = theme or self.theme_manager.current_theme()
        t = self._active_theme
        # OPT-01 (startup main-thread): apply_theme re-runs ~15 setStyleSheet calls
        # (incl. _apply_field_styling over 11 fields, each a large QSS block) and is
        # invoked several times during construction (setup_ui line 89, __init__ line 29,
        # _hp_layout.apply_theme, home_panel) with the SAME theme — a measured ~2.3 s
        # startup freeze (stall trace: apply_theme -> _apply_field_styling). Every
        # stylesheet here is a pure function of the theme dict, so re-applying an
        # unchanged theme is redundant work with a byte-identical visual result. Skip
        # when the theme is unchanged since the last successful application. All
        # styleable child widgets are created in setup_ui() BEFORE the first apply_theme,
        # so nothing is left unstyled. Kill switch: AIPACS_THEME_APPLY_DEDUP=0 restores
        # the byte-identical always-apply behavior; a real theme change (themeChanged ->
        # a different dict) never matches and always re-applies.
        if os.getenv("AIPACS_THEME_APPLY_DEDUP", "1") != "0":
            try:
                if t is not None and getattr(self, "_applied_theme_sig", None) == t:
                    return
            except Exception:
                pass
        self.setStyleSheet(f"background: {t['panel_bg']};")
        if hasattr(self, "search_group"):
            self.search_group.setStyleSheet(
                f"""
                QGroupBox {{
                    font-size: 14pt;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    margin: 4px 0px;
                    padding-top: 10px;
                    background: {t['panel_bg']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 8px 0 8px;
                    background: {t['panel_bg']};
                    border-radius: 5px;
                    color: {t['text_primary']};
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                    font-size: 13pt;
                }}
                """
            )
        if hasattr(self, "modality_group"):
            self.modality_group.setStyleSheet(
                f"""
                QGroupBox {{
                    font-size: 14pt;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                    border: 0px solid {t['border']};
                    margin: 4px 0px;
                    padding-top: 8px;
                    background: {t['panel_bg']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 8px 0 8px;
                    background: {t['panel_bg']};
                    border-radius: 5px;
                    color: {t['text_primary']};
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                    font-size: 13pt;
                }}
                """
            )
        if hasattr(self, "search_btn"):
            self.search_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['success']}, stop:1 {t['success_hover']});
                    color: #ffffff;
                    border: 1px solid {t['success']};
                    border-radius: 7px;
                    padding: 8px 14px;
                    font-size: 13pt;
                    font-family: 'Roboto', sans-serif;
                    margin: 0px;
                    letter-spacing: 0.5px;
                }}
                QPushButton:hover {{
                    border-color: {t['success_hover']};
                }}
                """
            )
            # V2 parallel design (opt-in, default OFF): keep Search on the accent
            # primary style after theme re-applies. No-op unless home == v2.
            try:
                from PacsClient.utils.v2_style import apply_search_button_v2
                apply_search_button_v2(self.search_btn)
            except Exception:
                pass
        if hasattr(self, "cancel_search_btn"):
            self.cancel_search_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['danger']}, stop:1 {t['danger_hover']});
                    color: #ffffff;
                    border: 1px solid {t['danger']};
                    border-radius: 7px;
                    padding: 8px 14px;
                    font-size: 13pt;
                    font-family: 'Roboto', sans-serif;
                    margin: 0px;
                    letter-spacing: 0.5px;
                }}
                """
            )
        self._apply_field_styling(t)
        self._apply_date_field_styling(t)
        # Remember the applied theme so an identical re-apply (redundant construction-time
        # call, or _hp_layout/home_panel re-theming with the same theme) is skipped above.
        self._applied_theme_sig = t

    def _on_date_selector_activated(self, _index):
        """Re-apply the active preset on every user pick (even the same one)."""
        self._on_date_selector_changed(self.date_selector.currentText())

    def _open_advanced_search_dialog(self):
        """Open the structured advanced-search popup; emit its query on accept."""
        try:
            from PacsClient.pacs.workstation_ui.home_ui.advanced_search_dialog import (
                AdvancedSearchDialog,
            )
            dialog = AdvancedSearchDialog(self)
            # Pre-fill from the simple field so a typed ID carries over.
            simple_id = self.patient_id_edit.text().strip()
            if simple_id:
                dialog.ids_edit.setPlainText(simple_id)
            if dialog.exec():
                self.advancedSearchRequested.emit(dialog.get_query())
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "Advanced search dialog failed: %s", exc, exc_info=True
            )

    def _on_date_selector_changed(self, text):
        """Handle date selector combo box changes"""
        current_data = self.date_selector.currentData()
        current_date = QDate.currentDate()

        if current_data == "all_dates":
            self.date_from_edit.setDate(QDate(1900, 1, 1))
            self.date_to_edit.setDate(QDate(2099, 12, 31))
        elif current_data == "today":
            self.date_from_edit.setDate(current_date)
            self.date_to_edit.setDate(current_date)
        elif current_data == "yesterday":
            yesterday = current_date.addDays(-1)
            self.date_from_edit.setDate(yesterday)
            self.date_to_edit.setDate(yesterday)
        elif current_data == 'two_days_ago':
            two_days_ago = current_date.addDays(-2)
            self.date_from_edit.setDate(two_days_ago)
            self.date_to_edit.setDate(two_days_ago)
        elif current_data == "last_week":
            last_week = current_date.addDays(-7)
            self.date_from_edit.setDate(last_week)
            self.date_to_edit.setDate(current_date)
        elif current_data == "last_month":
            last_month = current_date.addDays(-30)
            self.date_from_edit.setDate(last_month)
            self.date_to_edit.setDate(current_date)
        elif current_data == "last_year":
            last_year = current_date.addDays(-365)
            self.date_from_edit.setDate(last_year)
            self.date_to_edit.setDate(current_date)

    def _on_search_clicked(self):
        """Handle search button click"""
        is_valid, error_message = self.validate_search_data()

        if not is_valid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Search Validation Error", error_message)
            return

        self.searchRequested.emit()

    def get_checked_modalities(self):
        lst_checked = []
        for key, checkbox in self.modality_checks.items():
            checkbox: QCheckBox
            if checkbox.isChecked():
                lst_checked.append(key)

        lst_checked = ','.join(map(str, lst_checked))
        return lst_checked

    def get_search_data(self):
        """
        Get all search field values as a dictionary
        """
        date_from = self.date_from_edit.date().toString(
            "yyyyMMdd") if self.date_from_edit.date().isValid() else QDate.currentDate().toString("yyyyMMdd")
        date_to = self.date_to_edit.date().toString(
            "yyyyMMdd") if self.date_to_edit.date().isValid() else QDate.currentDate().toString("yyyyMMdd")

        lst_modality = self.get_checked_modalities()

        return {
            'patient_id': self.patient_id_edit.text(),
            'patient_name': self.patient_name_edit.text(),
            'patient_sex': self.patient_sex.text(),
            'study_id': self.study_id.text(),
            'date_from': date_from,
            'date_to': date_to,
            'study_description': self.study_description.text(),
            'series_description': self.series_description.text(),
            'modality': lst_modality,
            'request_type': self.request_type.currentData()
        }

    def clear_search_fields(self):
        """Clear all search fields"""
        self.patient_id_edit.clear()
        self.patient_name_edit.clear()
        self.patient_sex.clear()
        self.study_id.clear()
        self.date_selector.setCurrentIndex(0)
        self.date_from_edit.setDate(QDate.currentDate())
        self.date_to_edit.setDate(QDate.currentDate())
        self.study_description.clear()
        self.series_description.clear()
        self.modality.setCurrentIndex(0)
        self.request_type.setCurrentIndex(0)

    def set_search_data(self, data):
        """
        Set search field values from a dictionary
        """
        if 'patient_id' in data:
            self.patient_id_edit.setText(data['patient_id'])
        if 'patient_name' in data:
            self.patient_name_edit.setText(data['patient_name'])
        if 'patient_sex' in data:
            self.patient_sex.setText(data['patient_sex'])
        if 'study_id' in data:
            self.study_id.setText(data['study_id'])

        if 'date_from' in data and data['date_from']:
            try:
                date_str = data['date_from']
                if len(date_str) == 8:
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    self.date_from_edit.setDate(QDate(year, month, day))
            except (ValueError, IndexError):
                pass

        if 'date_to' in data and data['date_to']:
            try:
                date_str = data['date_to']
                if len(date_str) == 8:
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    self.date_to_edit.setDate(QDate(year, month, day))
            except (ValueError, IndexError):
                pass

        if 'study_date' in data and data['study_date'] and 'date_from' not in data:
            try:
                date_str = data['study_date']
                if len(date_str) == 8:
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    self.date_from_edit.setDate(QDate(year, month, day))
                    self.date_to_edit.setDate(QDate(year, month, day))
            except (ValueError, IndexError):
                pass

        if 'study_description' in data:
            self.study_description.setText(data['study_description'])
        if 'series_description' in data:
            self.series_description.setText(data['series_description'])

        if 'modality' in data and data['modality']:
            for i in range(self.modality.count()):
                if self.modality.itemData(i) == data['modality']:
                    self.modality.setCurrentIndex(i)
                    break

        if 'request_type' in data and data['request_type']:
            for i in range(self.request_type.count()):
                if self.request_type.itemData(i) == data['request_type']:
                    self.request_type.setCurrentIndex(i)
                    break

    def has_search_criteria(self):
        """
        Check if any search criteria has been entered
        """
        search_data = self.get_search_data()
        return any(value.strip() for key, value in search_data.items() if key not in ['date_from', 'date_to']) or \
               search_data['date_from'] or search_data['date_to']

    def get_search_summary(self):
        """
        Get a summary of the current search criteria
        """
        search_data = self.get_search_data()
        criteria = []

        if search_data['patient_id']:
            criteria.append(f"Patient ID: {search_data['patient_id']}")
        if search_data['patient_name']:
            criteria.append(f"Patient Name: {search_data['patient_name']}")
        if search_data['patient_sex']:
            criteria.append(f"Gender: {search_data['patient_sex']}")
        if search_data['study_id']:
            criteria.append(f"Study ID: {search_data['study_id']}")

        if search_data['date_from'] or search_data['date_to']:
            date_from_display = self.date_from_edit.date().toString("yyyy-MM-dd")
            date_to_display = self.date_to_edit.date().toString("yyyy-MM-dd")
            if date_from_display == date_to_display:
                criteria.append(f"Date: {date_from_display}")
            else:
                criteria.append(f"Date Range: {date_from_display} to {date_to_display}")

        if search_data['study_description']:
            criteria.append(f"Study Description: {search_data['study_description']}")
        if search_data['series_description']:
            criteria.append(f"Series Description: {search_data['series_description']}")
        if search_data['modality']:
            criteria.append(f"Modality: {search_data['modality']}")
        if search_data['request_type']:
            criteria.append(f"Request Type: {search_data['request_type']}")

        return " | ".join(criteria) if criteria else "No search criteria specified"

    def validate_search_data(self):
        """
        Validate the search data for common format issues
        """
        search_data = self.get_search_data()
        errors = []

        if search_data['patient_sex']:
            valid_sex = ['M', 'F', 'O', 'm', 'f', 'o']
            if search_data['patient_sex'] not in valid_sex:
                errors.append("Patient sex must be M, F, or O")

        if errors:
            return False, "\n".join(errors)

        return True, ""
