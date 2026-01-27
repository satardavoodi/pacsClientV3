import json
from pathlib import Path
from typing import Dict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QComboBox, QMessageBox,
    QToolButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

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
            border: 1px solid #2b313b;
            border-radius: 10px;
            padding: 6px;
        }
        QPushButton {
            background-color: #1b2230;
            border: 1px solid #2b313b;
            border-radius: 4px;
        }
        QPushButton[selected="true"] {
            background-color: #2563eb;
        }
        """)

        layout = QGridLayout(self)
        layout.setSpacing(4)

        self.buttons = {}
        for r in range(max_size):
            for c in range(max_size):
                btn = QPushButton()
                btn.setFixedSize(22, 22)
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
        self.setFixedWidth(90)
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
        QLabel {
            color: #e5e7eb;
        }
        QPushButton {
            background-color: #1b2230;
            border: 1px solid #2b313b;
            border-radius: 8px;
            padding: 6px 12px;
        }
        QPushButton[role="success"] {
            background-color: #16a34a;
            font-weight: 600;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title = QLabel("Modality Grid Layout")
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(title, alignment=Qt.AlignLeft)

        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(14)

        # ---------- Grid ----------
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)

        for i, h in enumerate(["Modality", "Layout", ""]):
            lbl = QLabel(h)
            lbl.setStyleSheet("font-weight: 600;")
            self.grid.addWidget(lbl, 0, i)

        card_layout.addLayout(self.grid)

        # ---------- Add Row ----------
        add_row = QHBoxLayout()

        self.new_name = QComboBox()
        self.new_name.setEditable(True)
        self.new_name.setFixedWidth(100)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(self.GRID_PRESETS.keys())
        self.preset_combo.setFixedWidth(90)

        add_btn = QPushButton("Add")
        add_btn.setProperty("role", "success")
        add_btn.clicked.connect(self.add_modality)

        add_row.addWidget(QLabel("Name"))
        add_row.addWidget(self.new_name)
        add_row.addSpacing(8)
        add_row.addWidget(QLabel("Grid"))
        add_row.addWidget(self.preset_combo)
        add_row.addSpacing(12)
        add_row.addWidget(add_btn)
        add_row.addStretch(1)

        card_layout.addLayout(add_row)

        # ---------- Bottom ----------
        bottom = QHBoxLayout()

        save = QPushButton("Save")
        save.setProperty("role", "success")
        save.clicked.connect(self.save_config)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.load_config)

        bottom.addWidget(save)
        bottom.addWidget(reload_btn)
        bottom.addStretch(1)

        card_layout.addLayout(bottom)
        root.addWidget(card, alignment=Qt.AlignLeft)
        root.addStretch(1)

    # --------------------------------------------------
    # Logic
    # --------------------------------------------------
    def load_config(self):
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config_data = json.load(f)
        else:
            self.config_data = {
                k: {"rows": v[0], "cols": v[1]}
                for k, v in self.DEFAULT_LAYOUTS.items()
            }
        self._rebuild()

    def _rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()

        headers = ["Modality", "Layout", "", "Modality", "Layout", ""]
        for i, h in enumerate(headers):
            self.grid.addWidget(QLabel(h), 0, i)

        self.modality_widgets.clear()

        items = list(self.config_data.items())
        row = 1
        col_block = 0  # 0 یا 1 (ستون چپ / راست)

        for name, cfg in items:
            base_col = col_block * 3

            lbl = QLabel(name)
            lbl.setFixedWidth(80)

            picker = GridPickerButton(cfg["rows"], cfg["cols"])

            rm = QToolButton()
            rm.setText("✕")
            rm.setFixedWidth(28)
            rm.clicked.connect(lambda _, m=name: self.remove_modality(m))

            self.grid.addWidget(lbl, row, base_col + 0)
            self.grid.addWidget(picker, row, base_col + 1)
            self.grid.addWidget(rm, row, base_col + 2)

            self.modality_widgets[name] = picker

            # هر دو آیتم → برو ردیف بعد
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

        self.configChanged.emit()
        QMessageBox.information(self, "Saved", "Grid configuration saved.")
