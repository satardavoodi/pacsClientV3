from PySide6.QtWidgets import (
    QMainWindow, QVBoxLayout, QTabWidget, QHBoxLayout, QWidget, QLabel
)
from .service_tab import ImagingToolsTab, ModelTrainingTab, ReceptionDataTab, DataSetTab
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget
)
from .service_tab import ImagingToolsTab, ModelTrainingTab, ReceptionDataTab, DataSetTab
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication


class AiMainWindow(QMainWindow):
    # Signal emitted when Eagle Eye is fully loaded and ready
    eagle_eye_ready = Signal()
    
    def __init__(self, study_uid=None):
        print("\n" + "=" * 80)
        print("[AiMainWindow] Initializing AiMainWindow.")
        print("=" * 80)
        super().__init__()
        
        self._apply_dark_theme()

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # Imaging Tools
        self.imaging_tab = ImagingToolsTab(study_uid=study_uid)
        self.tab_widget.addTab(self.imaging_tab, "Imaging Tools")

        # DataSet (KEEP REFERENCE!)
        self.dataset_tab = DataSetTab(study_uid=study_uid)
        self.tab_widget.addTab(self.dataset_tab, "Data Set")

        # Model Training
        self.model_training_tab = ModelTrainingTab()
        self.tab_widget.addTab(self.model_training_tab, "Model Training")

        # Reception Data
        try:
            self.reception_tab = ReceptionDataTab()
            self.tab_widget.addTab(self.reception_tab, "Reception Data")
        except Exception as e:
            print(f"[AiMainWindow] ERROR creating Reception Data tab: {e}")
            import traceback
            traceback.print_exc()

        # Auto refresh when user opens Data Set tab
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        QTimer.singleShot(0, self.dataset_tab.refresh)
        
        # Connect imaging tab ready signal
        self.imaging_tab.fully_loaded.connect(self._on_imaging_tab_ready)
        
        print("[AiMainWindow] AiMainWindow initialized successfully!")
        print("=" * 80 + "\n")

    def _on_imaging_tab_ready(self):
        """Called when ImagingToolsTab is fully loaded and rendered."""
        print("[AiMainWindow] Imaging tab fully loaded, emitting eagle_eye_ready signal")
        # Emit immediately - no delay needed
        self.eagle_eye_ready.emit()
    
    def _on_tab_changed(self, index: int):
        w = self.tab_widget.widget(index)
        if w is self.dataset_tab:
            self.dataset_tab.refresh()
        try:
            if w is self.imaging_tab:
                self.imaging_tab.patient_widget.on_tab_activated()
            else:
                self.imaging_tab.patient_widget.on_tab_deactivated()
        except Exception:
            pass

    def _apply_dark_theme(self):
        # بهتره برای یکنواختی QSS در ویندوز
        app = QApplication.instance()
        if app is not None:
            try:
                app.setStyle("Fusion")
            except Exception:
                pass

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
        self.dataset_tab.set_rows(rows)

    def append_dataset_rows(self, rows):
        self.dataset_tab.append_rows(rows)

    def set_dataset_csvs(self, csv_paths, *, refresh=True):
        self.dataset_tab.set_csv_paths(csv_paths, refresh=refresh)

    def refresh_dataset(self):
        self.dataset_tab.refresh()