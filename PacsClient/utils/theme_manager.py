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
        "accent_secondary": "#0284c7",
        "window_bg": "#18212f",
        "menu_bg": "#223246",
        "panel_bg": "#111927",
        "info": "#06b6d4",
        "info_subtle": "#164e63",
        "success": "#10b981",
        "success_subtle": "#064e3b",
        "warning": "#f59e0b",
        "warning_subtle": "#78350f",
        "danger": "#ef4444",
        "danger_subtle": "#7f1d1d",
        "badge_blue": "#1e40af",
        "badge_cyan": "#0369a1",
        "status_online": "#10b981",
        "status_offline": "#6b7280",
        "status_busy": "#ef4444",
    },
    "Gray": {
        "accent": "#8b95a7",
        "accent_secondary": "#71717a",
        "window_bg": "#1d2026",
        "menu_bg": "#30353d",
        "panel_bg": "#171b20",
        "info": "#64748b",
        "info_subtle": "#1e293b",
        "success": "#6b7280",
        "success_subtle": "#1f2937",
        "warning": "#9ca3af",
        "warning_subtle": "#374151",
        "danger": "#9f1239",
        "danger_subtle": "#1f2937",
        "badge_blue": "#475569",
        "badge_cyan": "#64748b",
        "status_online": "#6b7280",
        "status_offline": "#4b5563",
        "status_busy": "#9f1239",
    },
    "Green": {
        "accent": "#2f9e70",
        "accent_secondary": "#059669",
        "window_bg": "#15241e",
        "menu_bg": "#203b31",
        "panel_bg": "#12201b",
        "info": "#14b8a6",
        "info_subtle": "#134e4a",
        "success": "#2f9e70",
        "success_subtle": "#064e3b",
        "warning": "#84cc16",
        "warning_subtle": "#365314",
        "danger": "#f87171",
        "danger_subtle": "#7c2d12",
        "badge_blue": "#047857",
        "badge_cyan": "#0d9488",
        "status_online": "#2f9e70",
        "status_offline": "#6b7280",
        "status_busy": "#f87171",
    },
    "Turquoise": {
        "accent": "#20a4a5",
        "accent_secondary": "#0891b2",
        "window_bg": "#14252b",
        "menu_bg": "#1f3942",
        "panel_bg": "#102027",
        "info": "#06b6d4",
        "info_subtle": "#164e63",
        "success": "#14b8a6",
        "success_subtle": "#134e4a",
        "warning": "#fbbf24",
        "warning_subtle": "#78350f",
        "danger": "#f87171",
        "danger_subtle": "#7c2d12",
        "badge_blue": "#0891b2",
        "badge_cyan": "#20a4a5",
        "status_online": "#14b8a6",
        "status_offline": "#6b7280",
        "status_busy": "#f87171",
    },
    "Dark Red": {
        "accent": "#b63c57",
        "accent_secondary": "#a4151c",
        "window_bg": "#191015",
        "menu_bg": "#301a23",
        "panel_bg": "#120a0f",
        "info": "#d946a6",
        "info_subtle": "#500724",
        "success": "#ec4899",
        "success_subtle": "#500724",
        "warning": "#f97316",
        "warning_subtle": "#7c2d12",
        "danger": "#b63c57",
        "danger_subtle": "#6b1b28",
        "badge_blue": "#881337",
        "badge_cyan": "#b63c57",
        "status_online": "#ec4899",
        "status_offline": "#6b7280",
        "status_busy": "#b63c57",
    },
    "Yellow": {
        "accent": "#c99512",
        "accent_secondary": "#d97706",
        "window_bg": "#1f1b10",
        "menu_bg": "#3b3016",
        "panel_bg": "#171106",
        "info": "#f59e0b",
        "info_subtle": "#78350f",
        "success": "#eab308",
        "success_subtle": "#713f12",
        "warning": "#c99512",
        "warning_subtle": "#78350f",
        "danger": "#ea580c",
        "danger_subtle": "#7c2d12",
        "badge_blue": "#b45309",
        "badge_cyan": "#c99512",
        "status_online": "#eab308",
        "status_offline": "#6b7280",
        "status_busy": "#ea580c",
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
    accent_secondary = _normalize_hex(palette.get("accent_secondary", accent), accent)
    window_bg = _normalize_hex(palette.get("window_bg", "#18212f"), "#18212f")
    menu_bg = _normalize_hex(palette.get("menu_bg", "#223246"), "#223246")
    panel_bg = _normalize_hex(palette.get("panel_bg", "#111927"), "#111927")
    
    # Semantic colors from palette
    info = _normalize_hex(palette.get("info", "#06b6d4"), "#06b6d4")
    info_subtle = _normalize_hex(palette.get("info_subtle", "#164e63"), "#164e63")
    success = _normalize_hex(palette.get("success", "#10b981"), "#10b981")
    success_subtle = _normalize_hex(palette.get("success_subtle", "#064e3b"), "#064e3b")
    warning = _normalize_hex(palette.get("warning", "#f59e0b"), "#f59e0b")
    warning_subtle = _normalize_hex(palette.get("warning_subtle", "#78350f"), "#78350f")
    danger = _normalize_hex(palette.get("danger", "#ef4444"), "#ef4444")
    danger_subtle = _normalize_hex(palette.get("danger_subtle", "#7f1d1d"), "#7f1d1d")
    badge_blue = _normalize_hex(palette.get("badge_blue", "#1e40af"), "#1e40af")
    badge_cyan = _normalize_hex(palette.get("badge_cyan", "#0369a1"), "#0369a1")
    status_online = _normalize_hex(palette.get("status_online", "#10b981"), "#10b981")
    status_offline = _normalize_hex(palette.get("status_offline", "#6b7280"), "#6b7280")
    status_busy = _normalize_hex(palette.get("status_busy", "#ef4444"), "#ef4444")

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
        "accent_secondary": accent_secondary,
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
        "info": info,
        "info_subtle": info_subtle,
        "success": success,
        "success_subtle": success_subtle,
        "warning": warning,
        "warning_subtle": warning_subtle,
        "danger": danger,
        "danger_subtle": danger_subtle,
        "badge_blue": badge_blue,
        "badge_cyan": badge_cyan,
        "status_online": status_online,
        "status_offline": status_offline,
        "status_busy": status_busy,
        "success_hover": _shift_lightness(success, 12),
        "warning_hover": _shift_lightness(warning, 12),
        "danger_hover": _shift_lightness(danger, 12),
        "info_hover": _shift_lightness(info, 12),
        "neutral": _mix(text_muted, panel_bg, 0.5),
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
        # Allow customization of all semantic colors, not just the base four
        for key in ("accent", "accent_secondary", "window_bg", "menu_bg", "panel_bg",
                    "info", "success", "warning", "danger", "badge_blue", "badge_cyan",
                    "status_online", "status_offline", "status_busy"):
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
            
            # Load all theme colors with proper fallbacks
            blue_defaults = DEFAULT_THEMES["Blue"]
            self._settings["custom_theme"] = {
                "accent": _normalize_hex(custom.get("accent", blue_defaults.get("accent", "#3182ce")), "#3182ce"),
                "accent_secondary": _normalize_hex(custom.get("accent_secondary", blue_defaults.get("accent_secondary", "#0284c7")), "#0284c7"),
                "window_bg": _normalize_hex(custom.get("window_bg", blue_defaults.get("window_bg", "#18212f")), "#18212f"),
                "menu_bg": _normalize_hex(custom.get("menu_bg", blue_defaults.get("menu_bg", "#223246")), "#223246"),
                "panel_bg": _normalize_hex(custom.get("panel_bg", blue_defaults.get("panel_bg", "#111927")), "#111927"),
                "info": _normalize_hex(custom.get("info", blue_defaults.get("info", "#06b6d4")), "#06b6d4"),
                "info_subtle": _normalize_hex(custom.get("info_subtle", blue_defaults.get("info_subtle", "#164e63")), "#164e63"),
                "success": _normalize_hex(custom.get("success", blue_defaults.get("success", "#10b981")), "#10b981"),
                "success_subtle": _normalize_hex(custom.get("success_subtle", blue_defaults.get("success_subtle", "#064e3b")), "#064e3b"),
                "warning": _normalize_hex(custom.get("warning", blue_defaults.get("warning", "#f59e0b")), "#f59e0b"),
                "warning_subtle": _normalize_hex(custom.get("warning_subtle", blue_defaults.get("warning_subtle", "#78350f")), "#78350f"),
                "danger": _normalize_hex(custom.get("danger", blue_defaults.get("danger", "#ef4444")), "#ef4444"),
                "danger_subtle": _normalize_hex(custom.get("danger_subtle", blue_defaults.get("danger_subtle", "#7f1d1d")), "#7f1d1d"),
                "badge_blue": _normalize_hex(custom.get("badge_blue", blue_defaults.get("badge_blue", "#1e40af")), "#1e40af"),
                "badge_cyan": _normalize_hex(custom.get("badge_cyan", blue_defaults.get("badge_cyan", "#0369a1")), "#0369a1"),
                "status_online": _normalize_hex(custom.get("status_online", blue_defaults.get("status_online", "#10b981")), "#10b981"),
                "status_offline": _normalize_hex(custom.get("status_offline", blue_defaults.get("status_offline", "#6b7280")), "#6b7280"),
                "status_busy": _normalize_hex(custom.get("status_busy", blue_defaults.get("status_busy", "#ef4444")), "#ef4444"),
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
