from __future__ import annotations

from functools import partial

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PacsClient.utils.theme_manager import _theme_blueprint, get_theme_manager


class ThemeCustomizationDialog(QDialog):
    ROLE_LABELS = {
        "accent": "Accent",
        "window_bg": "Window",
        "menu_bg": "Menu",
        "panel_bg": "Panel",
    }

    def __init__(self, base_palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.theme_manager = get_theme_manager()
        self.theme = self.theme_manager.current_theme()
        self.colors = {
            "accent": base_palette.get("accent", self.theme["accent"]),
            "window_bg": base_palette.get("window_bg", self.theme["window_bg"]),
            "menu_bg": base_palette.get("menu_bg", self.theme["menu_bg"]),
            "panel_bg": base_palette.get("panel_bg", self.theme["panel_bg"]),
        }
        self._swatch_buttons: dict[str, QPushButton] = {}
        self._build_ui()
        self._refresh_preview()

    def custom_palette(self) -> dict[str, str]:
        return dict(self.colors)

    def _build_ui(self) -> None:
        self.setWindowTitle("Customize Theme")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        description = QLabel(
            "Build a custom workstation theme. Accent, window, menu, and panel colors "
            "are saved; the rest of the UI derives from these anchors automatically."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.preview_frame = QFrame(self)
        self.preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        self.preview_title = QFrame(self.preview_frame)
        self.preview_title.setMinimumHeight(34)  # Archetype 5
        preview_title_layout = QHBoxLayout(self.preview_title)
        preview_title_layout.setContentsMargins(12, 0, 12, 0)
        preview_title_layout.addWidget(QLabel("AIPacs Preview"))
        preview_title_layout.addStretch()
        preview_title_layout.addWidget(QLabel("Theme"))
        preview_layout.addWidget(self.preview_title)

        self.preview_body = QWidget(self.preview_frame)
        preview_body_layout = QHBoxLayout(self.preview_body)
        preview_body_layout.setContentsMargins(0, 0, 0, 0)
        preview_body_layout.setSpacing(0)

        self.preview_menu = QFrame(self.preview_body)
        self.preview_menu.setMinimumWidth(118)  # Archetype 5
        menu_layout = QVBoxLayout(self.preview_menu)
        menu_layout.setContentsMargins(12, 12, 12, 12)
        menu_layout.setSpacing(8)
        for label in ("Home", "Settings", "Theme"):
            menu_item = QLabel(label)
            menu_item.setObjectName("PreviewMenuItem")
            menu_layout.addWidget(menu_item)
        menu_layout.addStretch()
        preview_body_layout.addWidget(self.preview_menu)

        self.preview_content = QFrame(self.preview_body)
        content_layout = QVBoxLayout(self.preview_content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)
        self.preview_heading = QLabel("Theme panel preview")
        self.preview_heading.setObjectName("PreviewHeading")
        self.preview_text = QLabel("Preset cards, buttons, and tabs update instantly when the theme changes.")
        self.preview_text.setWordWrap(True)
        self.preview_button = QPushButton("Primary Action")
        self.preview_chip = QLabel("Active Theme")
        self.preview_chip.setObjectName("PreviewChip")
        content_layout.addWidget(self.preview_heading)
        content_layout.addWidget(self.preview_text)
        content_layout.addWidget(self.preview_button)
        content_layout.addWidget(self.preview_chip)
        content_layout.addStretch()
        preview_body_layout.addWidget(self.preview_content, 1)

        preview_layout.addWidget(self.preview_body)
        layout.addWidget(self.preview_frame)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        for row, role in enumerate(("accent", "window_bg", "menu_bg", "panel_bg")):
            label = QLabel(self.ROLE_LABELS[role])
            button = QPushButton(self.colors[role].upper())
            button.clicked.connect(partial(self._on_swatch_clicked, key=role))
            button.setMinimumHeight(34)
            self._swatch_buttons[role] = button
            grid.addWidget(label, row, 0)
            grid.addWidget(button, row, 1)

        layout.addLayout(grid)

        reset_btn = QPushButton("Reset To Current Theme")
        reset_btn.clicked.connect(self._reset_to_active_theme)
        layout.addWidget(reset_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {self.theme['panel_bg']};
                color: {self.theme['text_primary']};
            }}
            QLabel {{
                color: {self.theme['text_primary']};
            }}
            QPushButton {{
                background: {self.theme['panel_alt_bg']};
                color: {self.theme['text_primary']};
                border: 1px solid {self.theme['border']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QPushButton:hover {{
                border-color: {self.theme['accent']};
            }}
            """
        )

    def _pick_color(self, key: str) -> None:
        initial = QColor(self.colors[key])
        color = QColorDialog.getColor(initial, self, f"Select {self.ROLE_LABELS[key]} Color")
        if not color.isValid():
            return
        self.colors[key] = color.name(QColor.HexRgb)
        self._refresh_preview()

    def _on_swatch_clicked(self, _checked=False, *, key: str) -> None:
        self._pick_color(key)

    def _reset_to_active_theme(self) -> None:
        current = self.theme_manager.current_theme()
        self.colors = {
            "accent": current["accent"],
            "window_bg": current["window_bg"],
            "menu_bg": current["menu_bg"],
            "panel_bg": current["panel_bg"],
        }
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        t = _theme_blueprint(
            "Preview",
            {
                "accent": self.colors["accent"],
                "window_bg": self.colors["window_bg"],
                "menu_bg": self.colors["menu_bg"],
                "panel_bg": self.colors["panel_bg"],
            },
        )

        self.preview_frame.setStyleSheet(
            f"""
            QFrame {{
                border: 1px solid {t['border']};
                border-radius: 12px;
                background: {t['window_bg']};
            }}
            QFrame#PreviewMenuItem {{
                border: none;
            }}
            QLabel {{
                border: none;
            }}
            QLabel#PreviewHeading {{
                color: {t['text_primary']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#PreviewChip {{
                color: {t['button_text']};
                background: {t['accent']};
                border-radius: 10px;
                padding: 4px 10px;
                font-weight: 600;
            }}
            """
        )
        self.preview_title.setStyleSheet(
            f"background: {t['menu_bg']}; color: {t['text_primary']}; border-top-left-radius: 12px; border-top-right-radius: 12px;"
        )
        self.preview_menu.setStyleSheet(
            f"background: {t['menu_bg']}; color: {t['text_secondary']}; border-bottom-left-radius: 12px;"
        )
        self.preview_content.setStyleSheet(
            f"background: {t['panel_bg']}; color: {t['text_secondary']}; border-bottom-right-radius: 12px;"
        )
        self.preview_button.setStyleSheet(
            f"""
            QPushButton {{
                background: {t['accent']};
                color: {t['button_text']};
                border: 1px solid {t['accent']};
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {t['accent_hover']};
                border-color: {t['accent_hover']};
            }}
            """
        )
        for key, button in self._swatch_buttons.items():
            color = self.colors[key]
            button.setText(color.upper())
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: {color};
                    color: {'#111827' if QColor(color).lightness() > 150 else '#ffffff'};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-weight: 700;
                }}
                """
            )
