from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from PacsClient.utils.data_paths import USER_DATA_ROOT


THEME_STORAGE_DIR = USER_DATA_ROOT / "config"
THEME_STORAGE_PATH = THEME_STORAGE_DIR / "theme_settings.json"

DEFAULT_THEME_ORDER = ["Blue", "Gray", "Green", "Turquoise", "Dark Red", "Yellow", "Custom"]

DEFAULT_THEMES = {
    "Blue": {
        "accent": "#3182ce",
        "window_bg": "#18212f",
        "menu_bg": "#223246",
        "panel_bg": "#111927",
    },
    "Gray": {
        "accent": "#8b95a7",
        "window_bg": "#1d2026",
        "menu_bg": "#30353d",
        "panel_bg": "#171b20",
    },
    "Green": {
        "accent": "#2f9e70",
        "window_bg": "#15241e",
        "menu_bg": "#203b31",
        "panel_bg": "#12201b",
    },
    "Turquoise": {
        "accent": "#20a4a5",
        "window_bg": "#14252b",
        "menu_bg": "#1f3942",
        "panel_bg": "#102027",
    },
    "Dark Red": {
        "accent": "#b63c57",
        "window_bg": "#191015",
        "menu_bg": "#301a23",
        "panel_bg": "#120a0f",
    },
    "Yellow": {
        "accent": "#c99512",
        "window_bg": "#1f1b10",
        "menu_bg": "#3b3016",
        "panel_bg": "#171106",
    },
}


def _normalize_hex(color: str, fallback: str) -> str:
    qcolor = QColor(color)
    if not qcolor.isValid():
        qcolor = QColor(fallback)
    return qcolor.name(QColor.HexRgb)


def _mix(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, float(ratio)))
    qa = QColor(color_a)
    qb = QColor(color_b)
    if not qa.isValid():
        qa = QColor("#000000")
    if not qb.isValid():
        qb = QColor("#000000")
    red = round(qa.red() * (1.0 - ratio) + qb.red() * ratio)
    green = round(qa.green() * (1.0 - ratio) + qb.green() * ratio)
    blue = round(qa.blue() * (1.0 - ratio) + qb.blue() * ratio)
    return QColor(red, green, blue).name(QColor.HexRgb)


def _shift_lightness(color: str, delta: int) -> str:
    qcolor = QColor(color)
    if not qcolor.isValid():
        qcolor = QColor("#000000")
    hue, saturation, lightness, _alpha = qcolor.getHsl()
    if hue < 0:
        hue = 0
    if saturation < 0:
        saturation = 0
    if lightness < 0:
        lightness = 0
    lightness = max(0, min(255, lightness + delta))
    qcolor.setHsl(hue, saturation, lightness)
    return qcolor.name(QColor.HexRgb)


def _relative_luminance(color: str) -> float:
    qcolor = QColor(color)
    if not qcolor.isValid():
        qcolor = QColor("#000000")

    def _lin(channel: int) -> float:
        c = channel / 255.0
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r = _lin(qcolor.red())
    g = _lin(qcolor.green())
    b = _lin(qcolor.blue())
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _theme_blueprint(name: str, palette: dict[str, str]) -> dict[str, str]:
    accent = _normalize_hex(palette.get("accent", "#3182ce"), "#3182ce")
    window_bg = _normalize_hex(palette.get("window_bg", "#18212f"), "#18212f")
    menu_bg = _normalize_hex(palette.get("menu_bg", "#223246"), "#223246")
    panel_bg = _normalize_hex(palette.get("panel_bg", "#111927"), "#111927")

    text_primary = "#f8fafc"
    text_secondary = "#dbe7f3"
    text_muted = "#93a4b7"
    border = _mix(panel_bg, "#d7e3f4", 0.22)

    accent_hover = _shift_lightness(accent, 14)
    accent_pressed = _shift_lightness(accent, -18)
    button_text = "#0f172a" if _relative_luminance(accent) > 0.32 else "#ffffff"

    return {
        "name": name,
        "accent": accent,
        "accent_hover": accent_hover,
        "accent_pressed": accent_pressed,
        "accent_soft": _mix(panel_bg, accent, 0.28),
        "window_bg": window_bg,
        "window_alt_bg": _mix(window_bg, menu_bg, 0.4),
        "menu_bg": menu_bg,
        "menu_hover_bg": _mix(menu_bg, accent, 0.18),
        "menu_active_bg": _mix(menu_bg, accent, 0.33),
        "panel_bg": panel_bg,
        "panel_alt_bg": _shift_lightness(panel_bg, 9),
        "panel_deep_bg": _shift_lightness(panel_bg, -6),
        "card_bg": _mix(panel_bg, window_bg, 0.35),
        "border": border,
        "text_primary": text_primary,
        "text_secondary": text_secondary,
        "text_muted": text_muted,
        "tab_bg": _mix(menu_bg, panel_bg, 0.26),
        "tab_hover_bg": _mix(menu_bg, accent, 0.12),
        "tab_active_bg": accent,
        "button_text": button_text,
        "success": "#10b981",
        "success_hover": "#0e9f6e",
        "warning": "#f59e0b",
        "danger": "#ef4444",
        "danger_hover": "#dc2626",
        "neutral": "#64748b",
        "shadow": "rgba(0, 0, 0, 0.35)",
    }


class ThemeManager(QObject):
    themeChanged = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._settings = {
            "active_theme": "Blue",
            "custom_theme": deepcopy(DEFAULT_THEMES["Blue"]),
        }
        self._load()

    def theme_names(self) -> list[str]:
        return list(DEFAULT_THEME_ORDER)

    def current_theme_name(self) -> str:
        active = self._settings.get("active_theme", "Blue")
        return active if active in DEFAULT_THEME_ORDER else "Blue"

    def current_theme(self) -> dict[str, str]:
        return self.theme_by_name(self.current_theme_name())

    def theme_by_name(self, name: str) -> dict[str, str]:
        if name == "Custom":
            palette = deepcopy(self._settings.get("custom_theme") or DEFAULT_THEMES["Blue"])
        else:
            palette = deepcopy(DEFAULT_THEMES.get(name) or DEFAULT_THEMES["Blue"])
        return _theme_blueprint(name, palette)

    def current_custom_theme(self) -> dict[str, str]:
        return deepcopy(self._settings.get("custom_theme") or DEFAULT_THEMES["Blue"])

    def set_active_theme(self, name: str) -> dict[str, str]:
        theme_name = name if name in DEFAULT_THEME_ORDER else "Blue"
        self._settings["active_theme"] = theme_name
        self._save()
        theme = self.current_theme()
        self.themeChanged.emit(theme)
        return theme

    def update_custom_theme(self, palette: dict[str, str]) -> dict[str, str]:
        current = self.current_custom_theme()
        for key in ("accent", "window_bg", "menu_bg", "panel_bg"):
            if key in palette:
                current[key] = _normalize_hex(palette[key], current[key])
        self._settings["custom_theme"] = current
        self._settings["active_theme"] = "Custom"
        self._save()
        theme = self.current_theme()
        self.themeChanged.emit(theme)
        return theme

    def reset_custom_theme(self) -> dict[str, str]:
        self._settings["custom_theme"] = deepcopy(DEFAULT_THEMES["Blue"])
        self._settings["active_theme"] = "Blue"
        self._save()
        theme = self.current_theme()
        self.themeChanged.emit(theme)
        return theme

    def build_application_stylesheet(self, theme: dict[str, str] | None = None) -> str:
        t = theme or self.current_theme()
        return f"""
        QMessageBox {{
            background-color: {t['panel_bg']};
        }}
        QMessageBox QLabel {{
            color: {t['text_primary']};
            font-size: 13px;
        }}
        QMessageBox QPushButton {{
            background-color: {t['panel_alt_bg']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
            min-width: 90px;
        }}
        QMessageBox QPushButton:hover {{
            background-color: {t['accent']};
            border-color: {t['accent']};
        }}
        QMessageBox QPushButton:pressed {{
            background-color: {t['accent_pressed']};
            border-color: {t['accent_pressed']};
        }}
        QInputDialog, QFileDialog, QColorDialog, QFontDialog, QProgressDialog {{
            background-color: {t['panel_bg']};
        }}
        QInputDialog QLabel,
        QFileDialog QLabel,
        QColorDialog QLabel,
        QFontDialog QLabel,
        QProgressDialog QLabel {{
            color: {t['text_primary']};
            font-size: 13px;
        }}
        QInputDialog QLineEdit,
        QFileDialog QLineEdit,
        QColorDialog QLineEdit,
        QFontDialog QLineEdit {{
            background-color: {t['panel_alt_bg']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 13px;
        }}
        QFileDialog QTreeView,
        QFileDialog QListView,
        QFontDialog QListView {{
            background-color: {t['panel_alt_bg']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
        }}
        QFileDialog QTreeView::item:selected,
        QFileDialog QListView::item:selected,
        QFileDialog QComboBox QAbstractItemView {{
            selection-background-color: {t['accent']};
        }}
        QFileDialog QPushButton,
        QInputDialog QPushButton,
        QColorDialog QPushButton,
        QFontDialog QPushButton,
        QProgressDialog QPushButton {{
            background-color: {t['accent']};
            color: {t['button_text']};
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 70px;
        }}
        QFileDialog QPushButton:hover,
        QInputDialog QPushButton:hover,
        QColorDialog QPushButton:hover,
        QFontDialog QPushButton:hover,
        QProgressDialog QPushButton:hover {{
            background-color: {t['accent_hover']};
        }}
        QFileDialog QComboBox {{
            background-color: {t['panel_alt_bg']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
            border-radius: 4px;
            padding: 6px;
        }}
        QFileDialog QComboBox QAbstractItemView {{
            background-color: {t['panel_alt_bg']};
            color: {t['text_primary']};
        }}
        QProgressDialog QProgressBar {{
            background-color: {t['panel_alt_bg']};
            border: none;
            border-radius: 4px;
            text-align: center;
            color: {t['text_primary']};
        }}
        QProgressDialog QProgressBar::chunk {{
            background-color: {t['accent']};
            border-radius: 4px;
        }}
        QToolTip {{
            background-color: {t['panel_bg']};
            color: {t['text_primary']};
            border: 1px solid {t['border']};
            border-radius: 4px;
            padding: 4px 8px;
        }}
        *:focus {{
            outline: none;
        }}
        """

    def _load(self) -> None:
        try:
            if not THEME_STORAGE_PATH.exists():
                return
            with THEME_STORAGE_PATH.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            active = payload.get("active_theme", "Blue")
            if active not in DEFAULT_THEME_ORDER:
                active = "Blue"
            custom = payload.get("custom_theme") or deepcopy(DEFAULT_THEMES["Blue"])
            self._settings["active_theme"] = active
            self._settings["custom_theme"] = {
                "accent": _normalize_hex(custom.get("accent", "#3182ce"), "#3182ce"),
                "window_bg": _normalize_hex(custom.get("window_bg", "#18212f"), "#18212f"),
                "menu_bg": _normalize_hex(custom.get("menu_bg", "#223246"), "#223246"),
                "panel_bg": _normalize_hex(custom.get("panel_bg", "#111927"), "#111927"),
            }
        except Exception:
            self._settings = {
                "active_theme": "Blue",
                "custom_theme": deepcopy(DEFAULT_THEMES["Blue"]),
            }

    def _save(self) -> None:
        THEME_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_theme": self._settings["active_theme"],
            "custom_theme": self._settings["custom_theme"],
        }
        with THEME_STORAGE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)


_theme_manager: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
