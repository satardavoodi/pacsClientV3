from PySide6.QtWidgets import (
    QMainWindow, QVBoxLayout, QTabWidget, QHBoxLayout, QWidget, QLabel
)
from .service_tab.imaging_tab import ImagingToolsTab
from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication
import re
from PacsClient.utils.theme_manager import get_theme_manager


# ========== THEME RETINTING HELPERS ==========
def _ee_theme_color_map(theme: dict) -> dict:
    """Map hardcoded Eagle Eye window colors to theme-aware values."""
    return {
        "#0f1419": theme.get("panel_deep_bg", "#0f1419"),  # Main background
        "#f7fafc": theme.get("text_primary", "#f7fafc"),   # Primary text
        "#1a202c": theme.get("panel_bg", "#1a202c"),       # Panels
        "#2d3748": theme.get("border", "#2d3748"),         # Borders
        "#0b1015": theme.get("panel_deep_bg", "#0b1015"),  # Deep panels/inputs
        "#111827": theme.get("panel_deep_bg", "#111827"),  # Disabled/tab bg
        "#3182ce": theme.get("accent", "#3182ce"),         # Selection color
        "#6b7280": theme.get("text_muted", "#6b7280"),     # Disabled text
    }


def _ee_retint_stylesheet(css: str, theme: dict) -> str:
    """Replace hardcoded colors in CSS with theme-aware values."""
    out = css
    for old_color, new_color in _ee_theme_color_map(theme).items():
        out = re.sub(re.escape(old_color), new_color, out, flags=re.IGNORECASE)
    return out


def _ee_retint_widget_tree(root, theme: dict) -> None:
    """Recursively retint all widgets in the tree with theme colors."""
    if root is None:
        return
    
    # Retint this widget's own stylesheet
    own_sheet = root.styleSheet()
    if own_sheet:
        root.setStyleSheet(_ee_retint_stylesheet(own_sheet, theme))
    
    # Retint all child widgets
    try:
        for child in root.findChildren(type(root).__bases__[0]):
            child_sheet = child.styleSheet()
            if child_sheet:
                child.setStyleSheet(_ee_retint_stylesheet(child_sheet, theme))
    except Exception:
        pass


def normalize_eagle_eye_mode(mode):
    """Delegates to the shared authority (modules.ai_imaging.eagle_eye_modes).

    Kept as a module-level name because existing callers import it from here.
    """
    from modules.ai_imaging.eagle_eye_modes import normalize_eagle_eye_mode as _normalize
    return _normalize(mode)


class _LazyTabPlaceholder(QWidget):
    """Cheap first-paint placeholder for secondary Eagle Eye tools."""

    def __init__(self, key: str, title: str):
        super().__init__()
        self.lazy_tab_key = key
        layout = QVBoxLayout(self)
        label = QLabel(f"Open {title} to load its tools.")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)


class AiMainWindow(QMainWindow):
    # Signal emitted when Eagle Eye is fully loaded and ready
    eagle_eye_ready = Signal()
    
    def __init__(self, study_uid=None, eagle_eye_mode=None):
        print("\n" + "=" * 80)
        print("[AiMainWindow] Initializing AiMainWindow.")
        print("=" * 80)
        super().__init__()
        self.eagle_eye_mode = normalize_eagle_eye_mode(eagle_eye_mode)
        self._study_uid = study_uid
        
        self._apply_dark_theme()

        # ========== THEME RETINTING INITIALIZATION ==========
        self._app_theme_manager = get_theme_manager()
        self._app_theme = self._app_theme_manager.current_theme() if self._app_theme_manager else {}
        _ee_retint_widget_tree(self, self._app_theme)
        if self._app_theme_manager:
            self._app_theme_manager.themeChanged.connect(self._on_app_theme_changed)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        if self.eagle_eye_mode == 'brain_mri':
            from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
            self.imaging_tab = None
            self.brain_tab = BrainVolumetryWidget(study_uid=study_uid)
            self.tab_widget.addTab(self.brain_tab, 'Eagle Eye Brain')
            QTimer.singleShot(0, self.eagle_eye_ready.emit)
            QTimer.singleShot(0, self.brain_tab.choose_study_workflow)
            return

        # Imaging Tools
        self.imaging_tab = ImagingToolsTab(study_uid=study_uid, eagle_eye_mode=self.eagle_eye_mode)
        self.tab_widget.addTab(self.imaging_tab, "Imaging Tools")

        self.dataset_tab = None
        self.model_training_tab = None
        self.reception_tab = None
        self.brain_tab = None
        self._lazy_tab_placeholders = {}
        self._lazy_tab_building = set()
        self._install_lazy_tabs()

        # Sync reception context with PACS-backed imaging widget as soon as possible.
        self._sync_reception_patient_context()

        # Auto refresh when user opens Data Set tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        
        # Connect imaging tab ready signal
        self.imaging_tab.fully_loaded.connect(self._on_imaging_tab_ready)
        
        print("[AiMainWindow] AiMainWindow initialized successfully!")
        print("=" * 80 + "\n")

    def _install_lazy_tabs(self) -> None:
        for key, title in (
            ("brain", "Brain Volumetry"),
            ("dataset", "Data Set"),
            ("model_training", "Model Training"),
            ("reception", "Reception Data"),
        ):
            placeholder = _LazyTabPlaceholder(key, title)
            self._lazy_tab_placeholders[key] = placeholder
            self.tab_widget.addTab(placeholder, title)

    def _ensure_lazy_tab(self, key: str):
        existing = {
            "brain": self.brain_tab,
            "dataset": self.dataset_tab,
            "model_training": self.model_training_tab,
            "reception": self.reception_tab,
        }.get(key)
        if existing is not None or key in self._lazy_tab_building:
            return existing

        placeholder = self._lazy_tab_placeholders.get(key)
        index = self.tab_widget.indexOf(placeholder) if placeholder is not None else -1
        if index < 0:
            return None
        title = self.tab_widget.tabText(index)
        self._lazy_tab_building.add(key)
        try:
            if key == "brain":
                from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
                widget = BrainVolumetryWidget(study_uid=self._study_uid)
                self.brain_tab = widget
            elif key == "dataset":
                from .service_tab.dataset_tab import DataSetTab
                widget = DataSetTab(
                    study_uid=self._study_uid,
                    module_mode=self.eagle_eye_mode,
                )
                self.dataset_tab = widget
            elif key == "model_training":
                from .service_tab.model_tab import ModelTrainingTab
                widget = ModelTrainingTab()
                self.model_training_tab = widget
            elif key == "reception":
                from .service_tab.reception_data_tab import ReceptionDataTab
                widget = ReceptionDataTab()
                self.reception_tab = widget
            else:
                return None

            self.tab_widget.blockSignals(True)
            self.tab_widget.removeTab(index)
            self.tab_widget.insertTab(index, widget, title)
            self.tab_widget.setCurrentIndex(index)
            self.tab_widget.blockSignals(False)
            if placeholder is not None:
                placeholder.deleteLater()
            self._lazy_tab_placeholders.pop(key, None)

            if key == "dataset":
                widget.refresh()
            elif key == "reception":
                self._sync_reception_patient_context()
                widget.on_tab_activated()
            return widget
        except Exception as exc:
            self.tab_widget.blockSignals(False)
            print(f"[AiMainWindow] ERROR creating {title} tab: {exc}")
            return None
        finally:
            self._lazy_tab_building.discard(key)

    def refresh_ai_results(self) -> bool:
        """Re-read the MG AI manifest and refresh the left-panel "AI Results" dropdown.

        Called when an ALREADY-OPEN Eagle Eye tab is reused after a new analysis run
        (see `_hp_modules.add_new_tab_widget`), so every execution shows up as its own
        entry. Never raises into the caller.
        """
        if getattr(self, 'eagle_eye_mode', None) == 'brain_mri':
            QTimer.singleShot(0, self.brain_tab.choose_study_workflow)
            return True
        try:
            imaging_tab = getattr(self, 'imaging_tab', None)
            if imaging_tab is None:
                return False
            refresh = getattr(imaging_tab, 'refresh_mg_ai_results', None)
            if refresh is None:
                return False
            return bool(refresh())
        except RuntimeError:
            return False  # tab deleted
        except Exception as e:
            print(f"[AiMainWindow] refresh_ai_results failed: {e}")
            return False

    def _on_imaging_tab_ready(self):
        """Called when ImagingToolsTab is fully loaded and rendered."""
        self._sync_reception_patient_context()
        print("[AiMainWindow] Imaging tab fully loaded, emitting eagle_eye_ready signal")
        # Emit immediately - no delay needed
        self.eagle_eye_ready.emit()

    def _resolve_reception_patient_id(self):
        """Resolve patient_id for Reception tab from imaging widget, then DB fallback by study_uid."""
        # 1) Preferred: active imaging widget context
        try:
            imaging_tab = getattr(self, 'imaging_tab', None)
            patient_widget = getattr(imaging_tab, 'patient_widget', None) if imaging_tab is not None else None
            pid = getattr(patient_widget, 'patient_id', None) if patient_widget is not None else None
            if pid is not None and str(pid).strip() and str(pid).strip().lower() not in ("none", "null"):
                return str(pid).strip()
        except Exception:
            pass

        # 2) Fallback: lookup patient from study_uid in local DB (PACS source of truth)
        try:
            study_uid = getattr(self.imaging_tab, 'study_uid', None)
            if study_uid:
                from database.manager import get_patient_by_study_uid
                patient = get_patient_by_study_uid(study_uid)
                pid = (patient or {}).get('patient_id')
                if pid is not None and str(pid).strip() and str(pid).strip().lower() not in ("none", "null"):
                    return str(pid).strip()
        except Exception:
            pass

        return None

    def _sync_reception_patient_context(self):
        """Bind Reception tab to the same PACS patient context used by Imaging tab."""
        try:
            reception_tab = getattr(self, 'reception_tab', None)
            if reception_tab is None:
                return

            patient_id = self._resolve_reception_patient_id()
            if patient_id:
                reception_tab.set_patient_id(patient_id)
        except Exception:
            pass
    
    def _on_tab_changed(self, index: int):
        w = self.tab_widget.widget(index)
        lazy_key = getattr(w, "lazy_tab_key", None)
        if lazy_key:
            QTimer.singleShot(0, lambda key=lazy_key: self._ensure_lazy_tab(key))
            try:
                self.imaging_tab.patient_widget.on_tab_deactivated()
            except Exception:
                pass
            return
        if w is self.dataset_tab:
            self.dataset_tab.refresh()
        if hasattr(self, 'reception_tab') and w is self.reception_tab:
            self._sync_reception_patient_context()
            try:
                self.reception_tab.on_tab_activated()
            except Exception:
                pass
        try:
            if w is self.imaging_tab:
                self.imaging_tab.patient_widget.on_tab_activated()
            else:
                self.imaging_tab.patient_widget.on_tab_deactivated()
        except Exception:
            pass

    def _apply_dark_theme(self):
        # Avoid global app style mutation here. Re-applying Fusion at tab-open time
        # can repolish the full widget tree and block the main thread.

        self.setStyleSheet("""
            QWidget {
                background: #0f1419;
                color: #f7fafc;
                font-size: 12px;
            }

            QFrame, QGroupBox {
                background: #0f1419;
                border: 1px solid #1a202c;
                border-radius: 8px;
            }

            QLabel { background: transparent; }

            QPushButton {
                background: #1a202c;
                border: 1px solid #2d3748;
                padding: 6px 10px;
                border-radius: 6px;
            }
            QPushButton:hover { background: #2d3748; }
            QPushButton:pressed { background: #0b1015; }
            QPushButton:disabled { color: #6b7280; background: #111827; border-color: #111827; }

            QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
                background: #0b1015;
                border: 1px solid #2d3748;
                padding: 6px;
                border-radius: 6px;
                selection-background-color: #3182ce;
            }

            QComboBox {
                background: #0b1015;
                border: 1px solid #2d3748;
                padding: 5px 28px 5px 8px;
                border-radius: 6px;
            }
            QComboBox QAbstractItemView {
                background: #0b1015;
                border: 1px solid #2d3748;
                selection-background-color: #3182ce;
                outline: none;
            }

            QTabWidget::pane {
                border: 1px solid #1a202c;
                top: -1px;
            }
            QTabBar::tab {
                background: #111827;
                border: 1px solid #1a202c;
                padding: 8px 12px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }
            QTabBar::tab:selected { background: #1a202c; }

            QScrollBar:vertical, QScrollBar:horizontal {
                background: transparent;
                border: none;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background: #2d3748;
                border-radius: 6px;
                min-height: 20px;
                min-width: 20px;
            }
            QScrollBar::add-line, QScrollBar::sub-line { background: transparent; border: none; }
            QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        """)

    # -----------------------------
    # Public API for Eagle Eye
    # -----------------------------
    def set_dataset_rows(self, rows):
        tab = self._ensure_lazy_tab("dataset")
        if tab is not None:
            tab.set_rows(rows)

    def append_dataset_rows(self, rows):
        tab = self._ensure_lazy_tab("dataset")
        if tab is not None:
            tab.append_rows(rows)

    def set_dataset_csvs(self, csv_paths, *, refresh=True):
        tab = self._ensure_lazy_tab("dataset")
        if tab is not None:
            tab.set_csv_paths(csv_paths, refresh=refresh)

    def refresh_dataset(self):
        tab = self._ensure_lazy_tab("dataset")
        if tab is not None:
            tab.refresh()

    def _on_app_theme_changed(self, theme: dict) -> None:
        """Handle application theme changes and retint all UI elements."""
        try:
            self._app_theme = theme or (
                self._app_theme_manager.current_theme() if self._app_theme_manager else {}
            )
            _ee_retint_widget_tree(self, self._app_theme)
        except Exception as e:
            print(f"Error retinting AiMainWindow on theme change: {e}")
