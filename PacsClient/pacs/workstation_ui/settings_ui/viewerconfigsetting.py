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
from PacsClient.utils.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_VTK,
    load_viewer_backend,
    save_viewer_backend,
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
        layout.setSpacing(5)  # More spacing for easier clicking

        self.buttons = {}
        for r in range(max_size):
            for c in range(max_size):
                btn = QPushButton()
                btn.setFixedSize(29, 29)  # Larger cells for easier targeting
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
        self.setFixedWidth(100)  # Wider for better readability
        self.setMinimumHeight(34)  # Taller for easier clicking
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
            padding: 9px 14px;
            min-height: 36px;
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
            padding: 7px 11px;
            min-height: 34px;
            font-size: 14px;
        }
        QLabel {
            font-size: 14px;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)  # Generous padding
        root.setSpacing(16)

        title = QLabel("Viewer Configuration")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f3f4f6;")
        root.addWidget(title, alignment=Qt.AlignLeft)

        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(18)  # Larger spacing between sections

        # ---------- Two Columns ----------
        content_row = QHBoxLayout()
        content_row.setSpacing(18)  # More space between panels

        left_panel = QFrame()
        left_panel.setObjectName("Panel")
        left_panel_layout = QVBoxLayout(left_panel)
        left_panel_layout.setContentsMargins(16, 16, 16, 16)  # Generous padding
        left_panel_layout.setSpacing(14)

        right_panel = QFrame()
        right_panel.setObjectName("Panel")
        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(16, 16, 16, 16)  # Generous padding
        right_panel_layout.setSpacing(14)

        content_row.addWidget(left_panel, 3)
        content_row.addWidget(right_panel, 4)
        card_layout.addLayout(content_row)

        # ---------- Left: Grid ----------
        left_title = QLabel("Modality Grid Layout")
        left_title.setStyleSheet("font-weight: 600; font-size: 14px; color: #f9fafb;")
        left_panel_layout.addWidget(left_title)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)  # More horizontal space
        self.grid.setVerticalSpacing(13)  # More vertical space

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
        self.new_name.setFixedWidth(108)  # Wider for better readability

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.GRID_PRESETS.keys())
        self.preset_combo.setFixedWidth(90)  # Wider

        add_btn = QPushButton("Add")
        add_btn.setProperty("role", "success")
        add_btn.setMinimumWidth(90)
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

        # ---------- Viewer Mode (unified Fast / Advanced) ----------
        viewer_mode_row = QVBoxLayout()
        viewer_mode_row.setSpacing(10)

        viewer_mode_title = QLabel("Viewer Mode")
        viewer_mode_title.setStyleSheet("font-weight: 600; font-size: 14px; color: #f9fafb;")
        viewer_mode_row.addWidget(viewer_mode_title)

        self.viewer_mode_combo = QComboBox()
        self.viewer_mode_combo.addItem("⚡  Advanced  —  VTK + SimpleITK  |  Series Boost", "advanced")
        self.viewer_mode_combo.addItem("🚀  Fast  —  PyDicom  |  Local ±20 Boost", "fast")
        self.viewer_mode_combo.setMinimumHeight(36)
        self.viewer_mode_combo.setToolTip(
            "Advanced: VTK-based viewer with SimpleITK filters and full-series boost (Plan A / Plan B).\n"
            "Fast: PyDicom-based viewer with internal decoder and local ±20 slice boost."
        )
        viewer_mode_row.addWidget(self.viewer_mode_combo)

        viewer_mode_desc = QLabel(
            "Advanced: VTK rendering · SimpleITK filters · series-level boost (Plan A / Plan B).\n"
            "Fast: PyDicom rendering · built-in decoder · local ±20 slice window boost."
        )
        viewer_mode_desc.setStyleSheet(
            "color: #d1d5db; font-size: 13px; padding: 9px; "
            "background-color: #1f2937; border-radius: 4px; line-height: 1.5;"
        )
        viewer_mode_desc.setWordWrap(True)
        viewer_mode_row.addWidget(viewer_mode_desc)

        left_panel_layout.addLayout(viewer_mode_row)

        # Hidden widgets kept for backward-compat persistence helpers
        self.boostviewer_toggle = QCheckBox()
        self.boostviewer_toggle.setVisible(False)
        self.viewer_backend_combo = QComboBox()
        self.viewer_backend_combo.addItem("VTK / SimpleITK (Current)", BACKEND_VTK)
        self.viewer_backend_combo.addItem("PyDK (PyDicom 2D Lazy Load)", BACKEND_PYDICOM)
        self.viewer_backend_combo.setVisible(False)

        # ---------- Bottom ----------
        bottom = QHBoxLayout()
        bottom.setSpacing(15)

        save = QPushButton("💾  Save Configuration")
        save.setProperty("role", "success")
        save.setMinimumWidth(162)
        save.setMinimumHeight(36)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 700; }"
        )
        save.clicked.connect(self.save_config)

        reload_btn = QPushButton("🔄  Reload")
        reload_btn.setMinimumWidth(126)
        reload_btn.setMinimumHeight(36)
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
    def _create_default_config(self):
        """ایجاد فایل کانفیگ پیش‌فرض در صورت عدم وجود."""
        default_config = {
            "default": {
                "rows": 1,
                "cols": 2
            },
            "modality_layouts": {
                k: {"rows": v[0], "cols": v[1]}
                for k, v in self.DEFAULT_LAYOUTS.items()
            }
        }
        
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print(f"✅ Default modality config created: {self.config_path}")
        except Exception as e:
            print(f"❌ Error creating default config: {e}")

    def load_config(self):
        # ابتدا همه مودالیتی‌های پیش‌فرض را لود می‌کنیم
        self.config_data = {
            k: {"rows": v[0], "cols": v[1]}
            for k, v in self.DEFAULT_LAYOUTS.items()
        }

        # Load unified viewer mode and sync hidden compat widgets
        active_backend = load_viewer_backend(default=BACKEND_VTK)
        is_fast = active_backend in (BACKEND_PYDICOM, "pydicom_qt")
        mode_idx = self.viewer_mode_combo.findData("fast" if is_fast else "advanced")
        self.viewer_mode_combo.setCurrentIndex(max(0, mode_idx))
        self.boostviewer_toggle.setChecked(load_boost_viewer_enabled(default=True))
        idx = self.viewer_backend_combo.findData(active_backend)
        self.viewer_backend_combo.setCurrentIndex(max(0, idx))
        
        # اگر فایل کانفیگ وجود نداشت، آن را ایجاد می‌کنیم
        if not self.config_path.exists():
            print(f"⚠️ Modality config not found, creating default: {self.config_path}")
            self._create_default_config()
        
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
                print(f"❌ Error loading config: {e}")
                # در صورت خطا، فایل پیش‌فرض را دوباره ایجاد می‌کنیم
                self._create_default_config()
        
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
                "QToolButton { font-size: 16px; font-weight: bold; color: #e2e8f0; "
                "background-color: #1d4ed8; border: 1px solid #1e40af; border-radius: 6px; } "
                "QToolButton:hover { background-color: #1e40af; }"
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

        # ساختار JSON جدید با default و modality_layouts
        config_to_save = {
            "default": {
                "rows": 1,
                "cols": 2
            },
            "modality_layouts": self.config_data
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, indent=2, ensure_ascii=False)

        # Derive backend + boost from unified viewer mode
        viewer_mode = self.viewer_mode_combo.currentData()
        if viewer_mode == "fast":
            save_viewer_backend(BACKEND_PYDICOM)
            save_boost_viewer_enabled(True)   # boost always on in Fast (local ±20)
        else:
            save_viewer_backend(BACKEND_VTK)
            save_boost_viewer_enabled(True)   # boost always on in Advanced (series)

        self.configChanged.emit()
        QMessageBox.information(self, "Saved", "Grid configuration saved.")
        print(f"✅ Modality grid config saved: {self.config_path}")
