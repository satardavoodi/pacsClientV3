import json
from pathlib import Path
from typing import Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QComboBox, QMessageBox,
    QToolButton, QFrame, QSizePolicy, QCheckBox, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PacsClient.utils.boost_viewer_config import (
    load_boost_viewer_enabled,
    save_boost_viewer_enabled,
)
from .storage_cleanup_panel import StorageCleanupPanelWidget

try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"


# ============================================================
# Word-like Grid Picker Popup
# ============================================================
class GridPickerPopup(QFrame):
    gridSelected = Signal(int, int)

    def __init__(self, parent=None, max_size=6):
        super().__init__(parent, Qt.Popup)
        self.max_size = max_size

        self.setStyleSheet("""
        QFrame {
            background-color: #0f1319;
            border: 2px solid #3b82f6;
            border-radius: 10px;
            padding: 10px;
        }
        QPushButton {
            background-color: #1b2230;
            border: 2px solid #2b313b;
            border-radius: 4px;
        }
        QPushButton[selected="true"] {
            background-color: #2563eb;
            border: 2px solid #60a5fa;
        }
        """)

        layout = QGridLayout(self)
        layout.setSpacing(6)  # More spacing for easier clicking

        self.buttons = {}
        for r in range(max_size):
            for c in range(max_size):
                btn = QPushButton()
                btn.setFixedSize(32, 32)  # Larger cells for easier targeting
                btn.setCursor(Qt.PointingHandCursor)
                btn.enterEvent = lambda e, rr=r, cc=c: self._hover(rr, cc)
                btn.clicked.connect(lambda _, rr=r, cc=c: self._select(rr + 1, cc + 1))
                layout.addWidget(btn, r, c)
                self.buttons[(r, c)] = btn

    def _hover(self, r, c):
        for (rr, cc), b in self.buttons.items():
            b.setProperty("selected", rr <= r and cc <= c)
            b.style().unpolish(b)
            b.style().polish(b)

    def _select(self, rows, cols):
        self.gridSelected.emit(rows, cols)
        self.close()


# ============================================================
# Grid Picker Button
# ============================================================
class GridPickerButton(QPushButton):
    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(f"{rows} × {cols}", parent)
        self.rows = rows
        self.cols = cols
        self.setFixedWidth(110)  # Wider for better readability
        self.setMinimumHeight(38)  # Taller for easier clicking
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; }"
        )
        self.clicked.connect(self._open_picker)

    def _open_picker(self):
        popup = GridPickerPopup(self)
        popup.gridSelected.connect(self._set_grid)
        popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        popup.show()

    def _set_grid(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.setText(f"{rows} × {cols}")


# ============================================================
# Main Widget
# ============================================================
class ModalityGridConfigWidget(QWidget):
    configChanged = Signal()

    DEFAULT_LAYOUTS = {
        "CT": (1, 2),
        "MR": (1, 2),
        "MG": (2, 2),
        "CR": (1, 2),
        "DX": (1, 2),
        "US": (1, 2),
        "XA": (1, 2),
        "RF": (1, 2),
        "NM": (1, 2),
        "PT": (1, 2),
        "OT": (1, 2),
    }

    GRID_PRESETS = {
        "1 × 1": (1, 1),
        "1 × 2": (1, 2),
        "2 × 2": (2, 2),
        "3 × 3": (3, 3),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_path = GRID_CONFIG_PATH
        self.config_data: Dict[str, Dict[str, int]] = {}
        self.modality_widgets = {}
        self._setup_ui()
        self.load_config()

    # --------------------------------------------------
    # UI
    # --------------------------------------------------
    def _setup_ui(self):
        self.setStyleSheet("""
        QWidget {
            background-color: #0b0d10;
            color: #e5e7eb;
        }
        QFrame#Card {
            background-color: #10141a;
            border: 1px solid #232a33;
            border-radius: 12px;
        }
        QFrame#Panel {
            background-color: #0f1319;
            border: 1px solid #232a33;
            border-radius: 10px;
        }
        QLabel {
            color: #e5e7eb;
        }
        QPushButton {
            background-color: #1b2230;
            border: 1px solid #2b313b;
            border-radius: 8px;
            padding: 10px 16px;
            min-height: 40px;
            font-size: 14px;
            font-weight: 600;
        }
        QPushButton:hover {
            background-color: #252d3d;
        }
        QPushButton[role="success"] {
            background-color: #16a34a;
            font-weight: 700;
        }
        QPushButton[role="success"]:hover {
            background-color: #15803d;
        }
        QComboBox {
            background-color: #1b2230;
            border: 1px solid #2b313b;
            border-radius: 6px;
            padding: 8px 12px;
            min-height: 38px;
            font-size: 14px;
        }
        QLabel {
            font-size: 14px;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)  # Generous padding
        root.setSpacing(18)

        title = QLabel("Viewer Configuration")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #f3f4f6;")
        root.addWidget(title, alignment=Qt.AlignLeft)

        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(20)  # Larger spacing between sections

        # ---------- Two Columns ----------
        content_row = QHBoxLayout()
        content_row.setSpacing(20)  # More space between panels

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(18, 18, 18, 18)  # Generous padding
        left_panel_layout.setSpacing(16)

        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(18, 18, 18, 18)  # Generous padding
        right_panel_layout.setSpacing(16)

        content_row.addWidget(left_panel, 3)
        content_row.addWidget(right_panel, 4)
        card_layout.addLayout(content_row)

        # ---------- Left: Grid ----------
        left_title = QLabel("Modality Grid Layout")
        left_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        left_panel_layout.addWidget(left_title)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)  # More horizontal space
        self.grid.setVerticalSpacing(14)  # More vertical space

        for i, h in enumerate(["Modality", "Layout", ""]):
            lbl = QLabel(h)
            lbl.setStyleSheet("font-weight: 600; font-size: 14px; color: #d1d5db;")
            self.grid.addWidget(lbl, 0, i)

        left_panel_layout.addLayout(self.grid)

        # ---------- Add Row ----------
        add_row = QHBoxLayout()
        add_row.setSpacing(12)

        self.new_name = QComboBox()
        self.new_name.setEditable(True)
        self.new_name.setFixedWidth(120)  # Wider for better readability

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.GRID_PRESETS.keys())
        self.preset_combo.setFixedWidth(100)  # Wider

        add_btn = QPushButton("Add")
        add_btn.setProperty("role", "success")
        add_btn.setMinimumWidth(100)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.add_modality)

        name_label = QLabel("Name")
        name_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        grid_label = QLabel("Grid")
        grid_label.setStyleSheet("font-size: 14px; font-weight: 600;")

        add_row.addWidget(name_label)
        add_row.addWidget(self.new_name)
        add_row.addSpacing(12)
        add_row.addWidget(grid_label)
        add_row.addWidget(self.preset_combo)
        add_row.addSpacing(16)
        add_row.addWidget(add_btn)
        add_row.addStretch(1)

        left_panel_layout.addLayout(add_row)

        # ---------- Boost Viewer ----------
        boost_row = QVBoxLayout()
        boost_row.setSpacing(10)
        
        boost_title = QLabel("Boost Viewer")
        boost_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        boost_row.addWidget(boost_title)

        self.boostviewer_toggle = QCheckBox("Enable BoostViewer")
        self.boostviewer_toggle.setChecked(True)
        self.boostviewer_toggle.setStyleSheet(
            "QCheckBox { font-size: 14px; spacing: 10px; color: #e5e7eb; } "
            "QCheckBox::indicator { width: 20px; height: 20px; }"
        )
        self.boostviewer_toggle.setToolTip(
            "When enabled, automatic ZetaBoost warm-up runs on patient tab activation.\n"
            "When disabled, no automatic warm-up; only manually viewed series are cached."
        )
        boost_row.addWidget(self.boostviewer_toggle)

        boost_desc = QLabel(
            "ON: Automatic boost/warm-up on patient open.\n"
            "OFF: Manual-only mode (cache only what user drags/views)."
        )
        boost_desc.setStyleSheet(
            "color: #d1d5db; font-size: 13px; padding: 10px; "
            "background-color: #1f2937; border-radius: 4px; line-height: 1.5;"
        )
        boost_desc.setWordWrap(True)
        boost_row.addWidget(boost_desc)

        left_panel_layout.addLayout(boost_row)

        # ---------- Bottom ----------
        bottom = QHBoxLayout()
        bottom.setSpacing(15)

        save = QPushButton("💾  Save Configuration")
        save.setProperty("role", "success")
        save.setMinimumWidth(180)
        save.setMinimumHeight(45)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: 700; }"
        )
        save.clicked.connect(self.save_config)

        reload_btn = QPushButton("🔄  Reload")
        reload_btn.setMinimumWidth(140)
        reload_btn.setMinimumHeight(45)
        reload_btn.setCursor(Qt.PointingHandCursor)
        reload_btn.clicked.connect(self.load_config)

        bottom.addWidget(save)
        bottom.addWidget(reload_btn)
        bottom.addStretch(1)

        left_panel_layout.addLayout(bottom)
        left_panel_layout.addStretch(1)

        # ---------- Right: Local Storage Cleanup + Insights (Scrollable) ----------
        self.storage_cleanup_panel = StorageCleanupPanelWidget()

        storage_scroll_host = QWidget()
        storage_scroll_host_layout = QVBoxLayout(storage_scroll_host)
        storage_scroll_host_layout.setContentsMargins(0, 0, 0, 0)
        storage_scroll_host_layout.setSpacing(0)
        storage_scroll_host_layout.addWidget(self.storage_cleanup_panel)
        storage_scroll_host_layout.addStretch(1)

        storage_scroll_area = QScrollArea()
        storage_scroll_area.setWidgetResizable(True)
        storage_scroll_area.setFrameShape(QFrame.NoFrame)
        storage_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        storage_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        storage_scroll_area.setWidget(storage_scroll_host)
        storage_scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 12px; background: #111827; margin: 2px; border-radius: 6px; }"
            "QScrollBar::handle:vertical { background: #4b5563; min-height: 40px; border-radius: 6px; }"
            "QScrollBar::handle:vertical:hover { background: #6b7280; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        right_panel_layout.addWidget(storage_scroll_area, 1)

        root.addWidget(card, 1)

    # --------------------------------------------------
    # Logic
    # --------------------------------------------------
    def load_config(self):
        # ابتدا همه مودالیتی‌های پیش‌فرض را لود می‌کنیم
        self.config_data = {
            k: {"rows": v[0], "cols": v[1]}
            for k, v in self.DEFAULT_LAYOUTS.items()
        }

        # Load BoostViewer setting independently from modality grid config
        self.boostviewer_toggle.setChecked(load_boost_viewer_enabled(default=True))
        
        # اگر فایل کانفیگ وجود داشت، مقادیر آن را override می‌کنیم
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved_config = json.load(f)
                    # Extract modality_layouts if it exists, otherwise use the whole config
                    if "modality_layouts" in saved_config:
                        self.config_data.update(saved_config["modality_layouts"])
                    else:
                        # مقادیر ذخیره شده را به config_data اضافه/بروزرسانی می‌کنیم
                        self.config_data.update(saved_config)
            except Exception as e:
                print(f"Error loading config: {e}")
        
        self._rebuild()

    def _rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()

        headers = ["Modality", "Layout", "", "Modality", "Layout", ""]
        for i, h in enumerate(headers):
            header_label = QLabel(h)
            header_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #d1d5db;")
            self.grid.addWidget(header_label, 0, i)

        self.modality_widgets.clear()

        items = list(self.config_data.items())
        row = 1
        col_block = 0  # 0 or 1 (left / right column)

        for name, cfg in items:
            base_col = col_block * 3

            lbl = QLabel(name)
            lbl.setFixedWidth(100)  # Wider for readability
            lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #e5e7eb;")

            picker = GridPickerButton(cfg["rows"], cfg["cols"])

            rm = QToolButton()
            rm.setText("✕")
            rm.setFixedSize(36, 36)  # Larger clickable area
            rm.setCursor(Qt.PointingHandCursor)
            rm.setStyleSheet(
                "QToolButton { font-size: 16px; font-weight: bold; color: #ef4444; "
                "background-color: #7f1d1d; border: 1px solid #991b1b; border-radius: 6px; } "
                "QToolButton:hover { background-color: #991b1b; }"
            )
            rm.clicked.connect(lambda _, m=name: self.remove_modality(m))

            self.grid.addWidget(lbl, row, base_col + 0)
            self.grid.addWidget(picker, row, base_col + 1)
            self.grid.addWidget(rm, row, base_col + 2)

            self.modality_widgets[name] = picker

            # Every two items → go to next row
            if col_block == 1:
                row += 1
                col_block = 0
            else:
                col_block = 1

    def add_modality(self):
        name = self.new_name.currentText().strip().upper()
        if not name:
            return

        rows, cols = self.GRID_PRESETS[self.preset_combo.currentText()]
        self.config_data[name] = {"rows": rows, "cols": cols}
        self._rebuild()

    def remove_modality(self, name):
        if QMessageBox.question(self, "Remove", f"Remove {name}?") == QMessageBox.Yes:
            self.config_data.pop(name, None)
            self._rebuild()

    def save_config(self):
        for name, picker in self.modality_widgets.items():
            self.config_data[name] = {
                "rows": picker.rows,
                "cols": picker.cols,
            }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, indent=2)

        save_boost_viewer_enabled(self.boostviewer_toggle.isChecked())

        self.configChanged.emit()
        QMessageBox.information(self, "Saved", "Grid configuration saved.")