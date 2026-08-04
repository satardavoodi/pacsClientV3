"""Compact login / connection form controls (Windows-safe, unified field chrome)."""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt, QSize, Signal, QEvent, QDate
from PySide6.QtGui import QFont, QFontMetrics, QIntValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

FIELD_H = 40
_STEP_W = 26
_ICON_RAIL_W = 34
_ICON_SIZE = 18
_ICON_COLOR = "#e2e8f0"
_BORDER = "1px solid #64748b"
_BORDER_FOCUS = "1px solid #3b82f6"
_BORDER_HOVER = "1px solid #94a3b8"

_LINE_EDIT_QSS = f"""
    QLineEdit {{
        background-color: #121a26;
        color: #f8fafc;
        border: {_BORDER};
        border-radius: 8px;
        padding: 0 12px;
        font-size: 14px;
        font-weight: 500;
        min-height: 40px;
        max-height: 40px;
        selection-background-color: #2563eb;
        selection-color: #ffffff;
    }}
    QLineEdit:hover {{
        border: {_BORDER_HOVER};
        background-color: #162031;
    }}
    QLineEdit:focus {{
        border: {_BORDER_FOCUS};
        background-color: #152238;
    }}
"""


def _field_icon(name: str, color: str = _ICON_COLOR):
    return qta.icon(name, color=color)


# ── Trailing icon button geometry (2026-08-04) ───────────────────────────────
# The blue icon buttons at the right of every field (server chevron, Patient-ID
# advanced-search, Patient-Name, date-preset chevron, the two calendar buttons)
# are ALL built by the two helpers below, so their look is decided in exactly
# these two places.
#
# The original "rail" design meant the button to sit flush against the field's
# right edge: full-bleed, square on the left, rounded only on the right
# (`border-radius: 0 5px 5px 0`) with a 1px separator line. It never actually
# landed flush — the button is 34x(field_h-4) inside a shell of field_h with a
# 1px border, so at the Home page's field_h=36 it floated 1px inside the shell
# and its 5px right corners never lined up with the shell's 6px ones. A 5px
# radius on a 32px block is also barely a curve. Net effect: a chunky blue
# rectangle with visibly sharp corners, slightly too big for its field.
#
# It is now a CHIP: a square button, inset from the field edge, with a uniform
# radius on all four corners and no separator. Geometry comes from `setFixedSize`
# ONLY — the QSS no longer sets min/max-width, so there is a single authority for
# the size instead of two that could disagree.
#
# `AIPACS_FIELD_ICON_CHIP=0` restores the exact pre-2026-08-04 rail.
_CHIP_RADIUS = 6
_CHIP_INSET = 5          # gap between the chip and the field's inner right edge
_CHIP_MIN_SIDE = 22


def _icon_chip_enabled() -> bool:
    import os as _os
    return (_os.getenv("AIPACS_FIELD_ICON_CHIP", "1") or "1").strip() != "0"


def _chip_side(field_h: int) -> int:
    """Square chip side for a field of height ``field_h`` (36 -> 24, 40 -> 28)."""
    return max(_CHIP_MIN_SIDE, int(field_h) - 12)


def icon_rail_right_margin(field_h: int = FIELD_H) -> int:
    """Right contents-margin a field's root layout needs to inset the chip."""
    return _CHIP_INSET if _icon_chip_enabled() else 0


def _configure_icon_rail_button(
    btn: QToolButton,
    *,
    icon_name: str,
    tooltip: str,
    field_h: int,
    icon_size: int = _ICON_SIZE,
    icon_color: str = _ICON_COLOR,
    interactive: bool = True,
) -> None:
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    if _icon_chip_enabled():
        side = _chip_side(field_h)
        # Keep at least 4px of breathing room around the glyph, so the smaller
        # chip never looks stuffed (the calendar button asks for 18px).
        icon_size = min(int(icon_size), side - 8)
    btn.setIcon(_field_icon(icon_name, icon_color))
    btn.setIconSize(QSize(icon_size, icon_size))
    btn.setToolTip(tooltip)
    btn.setAutoRaise(False)
    if _icon_chip_enabled():
        side = _chip_side(field_h)
        # A fixed-size widget in the field's QHBoxLayout is centred vertically,
        # so a square chip is automatically inset by the same amount top+bottom.
        btn.setFixedSize(side, side)
    else:
        btn.setFixedSize(_ICON_RAIL_W, max(28, field_h - 4))
    if interactive:
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        btn.setProperty("decorative", "false")
    else:
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setProperty("decorative", "true")
    btn.style().unpolish(btn)
    btn.style().polish(btn)


def _icon_rail_btn_qss(selector: str, *, border: str, accent_soft: str, accent: str,
                       legacy_radius: int = 5) -> str:
    """QSS for a field's trailing icon button.

    ``legacy_radius`` only affects the kill-switch (rail) path, where the shell
    stylesheet used 6px and the themed one 5px — kept distinct so
    ``AIPACS_FIELD_ICON_CHIP=0`` reproduces the old look exactly.
    """
    if _icon_chip_enabled():
        # Uniform radius on all four corners, no separator, and NO width/height
        # rules — `_configure_icon_rail_button`'s setFixedSize is the only
        # authority for the geometry.
        return f"""
            {selector} {{
                background-color: {accent_soft};
                border: none;
                border-radius: {_CHIP_RADIUS}px;
                margin: 0;
                padding: 0;
            }}
            {selector}:hover {{
                background-color: {accent};
            }}
            {selector}:pressed {{
                background-color: {accent};
            }}
            {selector}[decorative="true"]:hover,
            {selector}[decorative="true"]:pressed {{
                background-color: {accent_soft};
            }}
        """
    return f"""
        {selector} {{
            background-color: {accent_soft};
            border: none;
            border-left: 1px solid {border};
            border-radius: 0 {legacy_radius}px {legacy_radius}px 0;
            margin: 0;
            padding: 0 2px;
            min-width: {_ICON_RAIL_W}px;
            max-width: {_ICON_RAIL_W}px;
            min-height: 28px;
        }}
        {selector}:hover {{
            background-color: {accent};
        }}
        {selector}:pressed {{
            background-color: {accent};
        }}
        {selector}[decorative="true"]:hover,
        {selector}[decorative="true"]:pressed {{
            background-color: {accent_soft};
        }}
    """


_FIELD_SHELL_QSS = f"""
    QWidget#LoginNumberField, QWidget#LoginComboField {{
        background-color: #121a26;
        border: {_BORDER};
        border-radius: 8px;
        min-height: 40px;
        max-height: 40px;
    }}
    QWidget#LoginNumberField:hover, QWidget#LoginComboField:hover {{
        border: {_BORDER_HOVER};
        background-color: #162031;
    }}
    QWidget#LoginNumberField[focus="true"], QWidget#LoginComboField[focus="true"] {{
        border: {_BORDER_FOCUS};
        background-color: #152238;
    }}
    QWidget#LoginNumberField QLabel#LoginFieldValue,
    QWidget#LoginNumberField QLineEdit#LoginFieldValue,
    QWidget#LoginComboField QLabel#LoginFieldValue {{
        background: transparent;
        border: none;
        color: #f8fafc;
        font-size: 14px;
        font-weight: 500;
        padding: 0 0 0 12px;
        selection-background-color: #2563eb;
        selection-color: #ffffff;
    }}
    QWidget#LoginNumberField QLabel#LoginFieldSuffix {{
        background: transparent;
        border: none;
        color: #94a3b8;
        font-size: 13px;
        font-weight: 500;
        padding: 0 4px 0 0;
    }}
    QWidget#LoginNumberField QToolButton#LoginFieldStep,
    QWidget#LoginComboField QToolButton#LoginFieldStep {{
        background: transparent;
        border: none;
        border-radius: 3px;
        padding: 0;
        margin: 0;
        min-width: 22px;
        max-width: 22px;
    }}
    QWidget#LoginNumberField QToolButton#LoginFieldStep:hover,
    QWidget#LoginComboField QToolButton#LoginFieldStep:hover {{
        background-color: rgba(37, 99, 235, 0.35);
    }}
    QWidget#LoginNumberField QToolButton#LoginFieldStep:pressed,
    QWidget#LoginComboField QToolButton#LoginFieldStep:pressed {{
        background-color: rgba(29, 78, 216, 0.55);
    }}
    {_icon_rail_btn_qss(
        "QWidget#LoginComboField QToolButton#LoginFieldChevron",
        border="#64748b",
        accent_soft="#1e3a5f",
        accent="#2563eb",
        legacy_radius=6,
    )}
"""

_COMBO_INNER_QSS = """
    QComboBox {
        background: transparent;
        border: none;
        color: #f8fafc;
        padding: 0 0 0 12px;
        font-size: 14px;
        font-weight: 500;
        min-height: 38px;
        max-height: 38px;
    }
    QComboBox::drop-down { width: 0; height: 0; border: none; }
    QComboBox::down-arrow { width: 0; height: 0; image: none; border: none; }
"""

_COMBO_POPUP_QSS = """
    QListView {
        background-color: #0f1724;
        color: #f1f5f9;
        border: 1px solid #3b82f6;
        border-radius: 8px;
        padding: 4px;
        outline: 0;
    }
    QListView::item {
        min-height: 32px;
        padding: 6px 10px;
        border-radius: 4px;
    }
    QListView::item:hover { background-color: #1e3a8a; color: #ffffff; }
    QListView::item:selected { background-color: #2563eb; color: #ffffff; }
"""


def _step_btn(parent: QWidget, icon_name: str, tooltip: str, slot) -> QToolButton:
    btn = QToolButton(parent)
    btn.setObjectName("LoginFieldStep")
    btn.setIcon(qta.icon(icon_name, color="#bfdbfe"))
    btn.setIconSize(QSize(10, 10))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    # Hold-to-repeat: without this the only way to move a value by more than one
    # is one click per unit.
    btn.setAutoRepeat(True)
    btn.setAutoRepeatDelay(400)
    btn.setAutoRepeatInterval(60)
    btn.clicked.connect(slot)
    return btn


class LoginNumberField(QWidget):
    """Numeric field — same shell as text inputs; compact inline steppers.

    The value is a REAL EDITABLE INPUT (``QLineEdit`` + ``QIntValidator``), not a
    label. It replaces a ``QSpinBox``, and the Welcome-page guard requires Host /
    Port / AE Title / Connection Timeout to stay typeable — with steppers alone,
    changing the socket port from 50052 to 104 is ~49,948 clicks.

    The suffix (e.g. " s") is a separate trailing label so it can never end up
    inside the editable text.
    """

    valueChanged = Signal(int)

    def __init__(
        self,
        parent=None,
        *,
        minimum: int = 1,
        maximum: int = 65535,
        value: int = 1,
        suffix: str = "",
    ):
        super().__init__(parent)
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self._suffix = str(suffix or "")
        self._value = int(value)

        self.setObjectName("LoginNumberField")
        self.setProperty("focus", "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(FIELD_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(_FIELD_SHELL_QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 2, 0)
        root.setSpacing(0)

        self._edit = QLineEdit(self)
        self._edit.setObjectName("LoginFieldValue")
        self._edit.setFrame(False)
        self._edit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._edit.setValidator(QIntValidator(self._minimum, self._maximum, self._edit))
        self._edit.setCursor(Qt.CursorShape.IBeamCursor)
        self._edit.editingFinished.connect(self._commit_text)
        self._edit.installEventFilter(self)
        self.setFocusProxy(self._edit)

        self._suffix_label = QLabel(self)
        self._suffix_label.setObjectName("LoginFieldSuffix")
        self._suffix_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._suffix_label.setVisible(bool(self._suffix))
        self._suffix_label.setText(self._suffix)

        step_col = QWidget(self)
        step_col.setFixedWidth(_STEP_W)
        step_layout = QVBoxLayout(step_col)
        step_layout.setContentsMargins(0, 4, 2, 4)
        step_layout.setSpacing(0)

        half = (FIELD_H - 8) // 2
        self._up_btn = _step_btn(step_col, "fa5s.chevron-up", "Increase", self._step_up)
        self._down_btn = _step_btn(step_col, "fa5s.chevron-down", "Decrease", self._step_down)
        self._up_btn.setFixedSize(_STEP_W - 2, half)
        self._down_btn.setFixedSize(_STEP_W - 2, half)
        for _b in (self._up_btn, self._down_btn):
            _b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        step_layout.addWidget(self._up_btn)
        step_layout.addWidget(self._down_btn)

        root.addWidget(self._edit, 1)
        root.addWidget(self._suffix_label)
        root.addWidget(step_col)

        self.setValue(value)

    # ── display ────────────────────────────────────────────────────────────
    def _refresh_display(self) -> None:
        text = str(self._value)
        if self._edit.text() != text:
            blocked = self._edit.blockSignals(True)
            self._edit.setText(text)
            self._edit.blockSignals(blocked)
        self._suffix_label.setText(self._suffix)
        self._suffix_label.setVisible(bool(self._suffix))

    def _set_focus_property(self, focused: bool) -> None:
        self.setProperty("focus", "true" if focused else "false")
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def eventFilter(self, obj, event):
        if obj is self._edit:
            etype = event.type()
            if etype == QEvent.Type.FocusIn:
                self._set_focus_property(True)
            elif etype == QEvent.Type.FocusOut:
                self._set_focus_property(False)
                self._commit_text()
        return super().eventFilter(obj, event)

    def _commit_text(self) -> None:
        """Clamp whatever was typed. An empty/invalid box reverts to the value."""
        raw = self._edit.text().strip()
        try:
            self.setValue(int(raw))
        except (TypeError, ValueError):
            self._refresh_display()

    # ── stepping ───────────────────────────────────────────────────────────
    def _step_up(self) -> None:
        self.setValue(self._value + 1)

    def _step_down(self) -> None:
        self.setValue(self._value - 1)

    # ── QSpinBox-compatible API ────────────────────────────────────────────
    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        clamped = max(self._minimum, min(self._maximum, int(value)))
        changed = clamped != self._value
        self._value = clamped
        self._refresh_display()
        if changed:
            self.valueChanged.emit(self._value)

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self._edit.setValidator(QIntValidator(self._minimum, self._maximum, self._edit))
        self.setValue(self._value)

    def setSuffix(self, suffix: str) -> None:
        self._suffix = str(suffix or "")
        self._refresh_display()

    def keyPressEvent(self, event):
        """Up/Down and PageUp/PageDown step, matching QSpinBox."""
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._step_up()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._step_down()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        """Only step when focused, so an accidental scroll over the form cannot
        silently change the port; otherwise let the parent scroll."""
        if not self._edit.hasFocus():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta > 0:
            self._step_up()
        elif delta < 0:
            self._step_down()
        event.accept()


class LoginComboField(QWidget):
    """Styled combo — Windows-safe shell + inline chevron (no native drop-down rail)."""

    currentIndexChanged = Signal(int)
    activated = Signal(int)
    currentTextChanged = Signal(str)

    def __init__(self, parent=None, *, field_h: int = FIELD_H):
        super().__init__(parent)
        self._field_h = int(field_h)
        self.setObjectName("LoginComboField")
        self.setProperty("focus", "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self._field_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(_FIELD_SHELL_QSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QHBoxLayout(self)
        # Right margin insets the trailing chip from the field's inner edge (0 on
        # the legacy flush-rail path) — see _configure_icon_rail_button.
        root.setContentsMargins(0, 0, icon_rail_right_margin(self._field_h), 0)
        root.setSpacing(0)

        self._combo = QComboBox(self)
        self._combo.setFixedHeight(max(28, self._field_h - 2))
        self._combo.setStyleSheet(_COMBO_INNER_QSS)
        self._combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        try:
            self._combo.view().setStyleSheet(_COMBO_POPUP_QSS)
        except Exception:
            pass
        self._combo.currentIndexChanged.connect(self.currentIndexChanged.emit)
        self._combo.activated.connect(self.activated.emit)
        self._combo.currentTextChanged.connect(self.currentTextChanged.emit)

        self._open_btn = QToolButton(self)
        self._open_btn.setObjectName("LoginFieldChevron")
        _configure_icon_rail_button(
            self._open_btn,
            icon_name="fa5s.chevron-down",
            tooltip="Open list",
            field_h=self._field_h,
            icon_size=16,
        )
        self._open_btn.clicked.connect(self._combo.showPopup)

        root.addWidget(self._combo, 1)
        root.addWidget(self._open_btn)

        self._combo.installEventFilter(self)

    def apply_theme(self, theme: dict, *, font_pt: int = 12, field_h: int | None = None) -> None:
        """Theme-aware styling for Home / Settings surfaces (uses theme_manager tokens)."""
        t = theme or {}
        h = int(field_h if field_h is not None else self._field_h)
        self._field_h = h
        self.setFixedHeight(h)
        self._combo.setFixedHeight(max(28, h - 2))

        bg = t.get("panel_alt_bg", "#121a26")
        card = t.get("card_bg", "#162031")
        border = t.get("border", "#64748b")
        accent = t.get("accent", "#3b82f6")
        text = t.get("text_primary", "#f8fafc")
        muted = t.get("text_muted", "#94a3b8")
        btn_text = t.get("button_text", "#ffffff")
        hover_bg = t.get("menu_hover_bg", card)
        accent_soft = t.get("accent_soft", "#1e3a5f")

        _configure_icon_rail_button(
            self._open_btn,
            icon_name="fa5s.chevron-down",
            tooltip="Open list",
            field_h=h,
            icon_size=16,
            icon_color=text,
        )

        self.setStyleSheet(f"""
            QWidget#LoginComboField {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 5px;
                min-height: {h}px;
                max-height: {h}px;
            }}
            QWidget#LoginComboField:hover {{
                border: 1px solid {accent};
                background-color: {card};
            }}
            {_icon_rail_btn_qss(
                "QWidget#LoginComboField QToolButton#LoginFieldChevron",
                border=border,
                accent_soft=accent_soft,
                accent=accent,
            )}
        """)
        self._combo.setStyleSheet(f"""
            QComboBox {{
                background: transparent;
                border: none;
                color: {text};
                padding: 0 0 0 10px;
                font-size: {font_pt}pt;
                font-family: 'Roboto', sans-serif;
                min-height: {max(26, h - 4)}px;
                max-height: {max(26, h - 4)}px;
            }}
            QComboBox::drop-down {{ width: 0; height: 0; border: none; }}
            QComboBox::down-arrow {{ width: 0; height: 0; image: none; border: none; }}
        """)
        try:
            self._combo.view().setStyleSheet(f"""
                QListView {{
                    background-color: {t.get('panel_bg', bg)};
                    color: {text};
                    border: 1px solid {accent};
                    border-radius: 5px;
                    padding: 4px;
                    outline: 0;
                    font-size: {font_pt}pt;
                }}
                QListView::item {{
                    min-height: 28px;
                    padding: 6px 10px;
                    border-radius: 4px;
                }}
                QListView::item:hover {{ background-color: {hover_bg}; }}
                QListView::item:selected {{
                    background-color: {accent};
                    color: {btn_text};
                }}
            """)
        except Exception:
            pass

    def setToolTip(self, tip: str) -> None:  # noqa: N802 — Qt API
        super().setToolTip(tip)
        self._combo.setToolTip(tip)
        self._open_btn.setToolTip(tip or "Open list")

    def eventFilter(self, obj, event):
        if obj is self._combo and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._combo.showPopup()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._combo.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def addItem(self, *args, **kwargs):
        return self._combo.addItem(*args, **kwargs)

    def clear(self) -> None:
        self._combo.clear()

    def currentIndex(self) -> int:
        return self._combo.currentIndex()

    def setCurrentIndex(self, index: int) -> None:
        self._combo.setCurrentIndex(index)

    def currentData(self, role: int = Qt.ItemDataRole.UserRole):
        return self._combo.currentData(role)

    def findData(self, data, role: int = Qt.ItemDataRole.UserRole) -> int:
        return self._combo.findData(data, role)

    def count(self) -> int:
        return self._combo.count()

    def currentText(self) -> str:
        return self._combo.currentText()

    def itemData(self, index: int, role: int = Qt.ItemDataRole.UserRole):
        return self._combo.itemData(index, role)


class LoginLineField(QWidget):
    """Styled text field — Windows-safe shell + optional trailing icon rail."""

    textChanged = Signal(str)
    returnPressed = Signal()
    actionTriggered = Signal()

    def __init__(
        self,
        parent=None,
        *,
        field_h: int = FIELD_H,
        trailing_icon: str | None = None,
        trailing_tooltip: str = "",
        trailing_action: bool = True,
    ):
        super().__init__(parent)
        self._field_h = int(field_h)
        self._trailing_icon = trailing_icon
        self._trailing_action = trailing_action
        self.setObjectName("LoginLineField")
        self.setProperty("focus", "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self._field_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        # Right margin insets the trailing chip from the field's inner edge (0 on
        # the legacy flush-rail path) — see _configure_icon_rail_button.
        root.setContentsMargins(0, 0, icon_rail_right_margin(self._field_h), 0)
        root.setSpacing(0)

        self._line = QLineEdit(self)
        self._line.setFixedHeight(max(28, self._field_h - 2))
        self._line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._line.setCursor(Qt.CursorShape.IBeamCursor)
        self._line.textChanged.connect(self.textChanged.emit)
        self._line.returnPressed.connect(self.returnPressed.emit)
        self._line.installEventFilter(self)

        root.addWidget(self._line, 1)

        self._action_btn: QToolButton | None = None
        if trailing_icon:
            self._action_btn = QToolButton(self)
            self._action_btn.setObjectName("LoginFieldAction")
            _configure_icon_rail_button(
                self._action_btn,
                icon_name=trailing_icon,
                tooltip=trailing_tooltip or "More options",
                field_h=self._field_h,
                icon_size=16,
                interactive=trailing_action,
            )
            if trailing_action:
                self._action_btn.clicked.connect(self.actionTriggered.emit)
            root.addWidget(self._action_btn)

    def lineEdit(self) -> QLineEdit:
        return self._line

    def actionButton(self) -> QToolButton | None:
        return self._action_btn

    def trailingActionEnabled(self) -> bool:
        return self._trailing_action

    def eventFilter(self, obj, event):
        if obj is self._line:
            if event.type() == QEvent.Type.FocusIn:
                self.setProperty("focus", "true")
                self.style().unpolish(self)
                self.style().polish(self)
            elif event.type() == QEvent.Type.FocusOut:
                self.setProperty("focus", "false")
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(obj, event)

    def apply_theme(
        self,
        theme: dict,
        *,
        font_pt: int = 12,
        field_h: int | None = None,
    ) -> None:
        t = theme or {}
        h = int(field_h if field_h is not None else self._field_h)
        self._field_h = h
        self.setFixedHeight(h)
        self._line.setFixedHeight(max(28, h - 2))

        bg = t.get("panel_alt_bg", "#121a26")
        card = t.get("card_bg", "#162031")
        border = t.get("border", "#64748b")
        accent = t.get("accent", "#3b82f6")
        accent_soft = t.get("accent_soft", "#1e3a5f")
        text = t.get("text_primary", "#f8fafc")
        muted = t.get("text_muted", "#94a3b8")
        btn_text = t.get("button_text", "#ffffff")

        action_qss = ""
        if self._action_btn is not None and self._trailing_icon:
            _configure_icon_rail_button(
                self._action_btn,
                icon_name=self._trailing_icon,
                tooltip=self._action_btn.toolTip() or "More options",
                field_h=h,
                icon_size=16,
                icon_color=text,
                interactive=self._trailing_action,
            )
            action_qss = _icon_rail_btn_qss(
                "QWidget#LoginLineField QToolButton#LoginFieldAction",
                border=border,
                accent_soft=accent_soft,
                accent=accent,
            )

        self.setStyleSheet(f"""
            QWidget#LoginLineField {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                min-height: {h}px;
                max-height: {h}px;
            }}
            QWidget#LoginLineField:hover {{
                border: 1px solid {accent};
                background-color: {card};
            }}
            QWidget#LoginLineField[focus="true"] {{
                border: 1px solid {accent};
                background-color: {card};
            }}
            {action_qss}
        """)
        self._line.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {text};
                padding: 0 0 0 10px;
                font-size: {font_pt}pt;
                font-family: 'Roboto', sans-serif;
                min-height: {max(26, h - 4)}px;
                max-height: {max(26, h - 4)}px;
                selection-background-color: {accent};
                selection-color: {btn_text};
            }}
            QLineEdit::placeholder {{
                color: {muted};
                font-style: italic;
            }}
        """)

    def setToolTip(self, tip: str) -> None:  # noqa: N802 — Qt API
        super().setToolTip(tip)
        self._line.setToolTip(tip)

    def text(self) -> str:
        return self._line.text()

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API
        self._line.setText(text)

    def clear(self) -> None:
        self._line.clear()

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 — Qt API
        self._line.setPlaceholderText(text)

    def setMaxLength(self, length: int) -> None:  # noqa: N802 — Qt API
        self._line.setMaxLength(length)


class _CalendarPopupPanel(QWidget):
    """Clinical date-picker popup: preview strip + grid + Today shortcut."""

    datePicked = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginDatePickerPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._preview = QLabel()
        self._preview.setObjectName("LoginDatePreview")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._calendar = QCalendarWidget()
        self._calendar.setGridVisible(True)
        self._calendar.clicked.connect(self.datePicked.emit)
        self._calendar.selectionChanged.connect(self._sync_preview)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        self._today_btn = QPushButton("Today")
        self._today_btn.setObjectName("LoginDateTodayBtn")
        self._today_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._today_btn.clicked.connect(self._pick_today)
        footer.addWidget(self._today_btn)

        root.addWidget(self._preview)
        root.addWidget(self._calendar)
        root.addLayout(footer)
        self._sync_preview()

    def calendar(self) -> QCalendarWidget:
        return self._calendar

    def setSelectedDate(self, date: QDate) -> None:
        self._calendar.setSelectedDate(date)
        self._sync_preview()

    def replace_calendar(self, widget: QCalendarWidget) -> None:
        if widget is self._calendar:
            return
        layout = self.layout()
        idx = layout.indexOf(self._calendar)
        try:
            self._calendar.clicked.disconnect(self.datePicked.emit)
            self._calendar.selectionChanged.disconnect(self._sync_preview)
        except Exception:
            pass
        self._calendar.setParent(None)
        self._calendar = widget
        widget.setGridVisible(True)
        widget.clicked.connect(self.datePicked.emit)
        widget.selectionChanged.connect(self._sync_preview)
        if idx >= 0:
            layout.insertWidget(idx, widget)
        self._sync_preview()

    def _sync_preview(self) -> None:
        picked = self._calendar.selectedDate()
        self._preview.setText(picked.toString("yyyy · MM · dd"))

    def _pick_today(self) -> None:
        today = QDate.currentDate()
        self._calendar.setSelectedDate(today)
        self._sync_preview()
        self.datePicked.emit(today)

    def apply_theme(
        self,
        theme: dict,
        *,
        calendar_pt: int = 11,
        first_day_of_week: Qt.DayOfWeek = Qt.DayOfWeek.Saturday,
    ) -> None:
        t = theme or {}
        bg = t.get("panel_bg", "#0f1419")
        card = t.get("card_bg", "#162031")
        border = t.get("border", "#475569")
        accent = t.get("accent", "#2563eb")
        accent_soft = t.get("accent_soft", "#1e3a5f")
        text = t.get("text_primary", "#f8fafc")
        muted = t.get("text_muted", "#94a3b8")
        btn_text = t.get("button_text", "#ffffff")
        hover_bg = t.get("menu_hover_bg", card)
        text_secondary = t.get("text_secondary", muted)

        self.setStyleSheet(f"""
            QWidget#LoginDatePickerPanel {{
                background-color: {bg};
            }}
            QLabel#LoginDatePreview {{
                color: {text};
                font-size: 15pt;
                font-weight: 600;
                font-family: 'Consolas', 'Roboto Mono', 'Roboto', monospace;
                letter-spacing: 0.5px;
                padding: 6px 4px 2px 4px;
                border-bottom: 1px solid {border};
            }}
            QPushButton#LoginDateTodayBtn {{
                background-color: transparent;
                color: {accent};
                border: 1px solid {accent};
                border-radius: 6px;
                padding: 4px 14px;
                font-size: {calendar_pt}pt;
                font-weight: 600;
            }}
            QPushButton#LoginDateTodayBtn:hover {{
                background-color: {accent_soft};
                color: {text};
            }}
        """)

        try:
            self._calendar.setFirstDayOfWeek(first_day_of_week)
            self._calendar.setHorizontalHeaderFormat(
                QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
            )
        except Exception:
            pass

        cal_f = QFont(self._calendar.font())
        cal_f.setPointSize(calendar_pt)
        self._calendar.setFont(cal_f)
        cfm = QFontMetrics(cal_f)
        cell_h = max(22, int(cfm.height() * 1.35))
        nav_h = max(26, int(cfm.height() * 1.6))
        self._calendar.setStyleSheet(f"""
            QCalendarWidget {{
                background: {bg};
                border: none;
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background: {card};
                border: 1px solid {border};
                border-radius: 6px;
                min-height: {nav_h}px;
                margin-bottom: 2px;
            }}
            QCalendarWidget QToolButton {{
                color: {text};
                background: transparent;
                font-size: {calendar_pt}pt;
                font-weight: 600;
                padding: 3px 8px;
                border-radius: 4px;
            }}
            QCalendarWidget QToolButton:hover {{ background: {hover_bg}; }}
            QCalendarWidget QAbstractItemView {{
                selection-background-color: {accent};
                selection-color: {btn_text};
                outline: none;
                font-size: {calendar_pt}pt;
                color: {text};
                background: {bg};
                gridline-color: transparent;
            }}
            QCalendarWidget QAbstractItemView:item {{
                min-height: {cell_h}px;
                min-width: {cell_h}px;
                margin: 1px;
                border-radius: 6px;
            }}
            QCalendarWidget QAbstractItemView:item:hover {{
                background: {accent_soft};
                color: {text};
            }}
            QCalendarWidget QTableView QHeaderView::section {{
                background: transparent;
                color: {text_secondary};
                font-size: {calendar_pt - 1}pt;
                font-weight: 600;
                padding: 4px 0;
                border: none;
            }}
        """)


class LoginDateField(QWidget):
    """Styled date field — clinical shell + calendar popup panel (Windows-safe)."""

    dateChanged = Signal(QDate)

    def __init__(self, parent=None, *, field_h: int = FIELD_H):
        super().__init__(parent)
        self._field_h = int(field_h)
        self.setObjectName("LoginDateField")
        self.setProperty("focus", "false")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(self._field_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QHBoxLayout(self)
        # Right margin insets the trailing chip from the field's inner edge (0 on
        # the legacy flush-rail path) — see _configure_icon_rail_button.
        root.setContentsMargins(0, 0, icon_rail_right_margin(self._field_h), 0)
        root.setSpacing(0)

        self._date_edit = QDateEdit(self)
        self._date_edit.setCalendarPopup(False)
        self._date_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setFixedHeight(max(28, self._field_h - 2))
        self._date_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._date_edit.setCursor(Qt.CursorShape.IBeamCursor)
        self._date_edit.dateChanged.connect(self.dateChanged.emit)
        self._date_edit.installEventFilter(self)

        date_font = QFont("Consolas")
        if not date_font.exactMatch():
            date_font = QFont("Roboto Mono")
        if not date_font.exactMatch():
            date_font = QFont("Roboto")
        date_font.setStyleHint(QFont.StyleHint.Monospace)
        date_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        self._date_edit.setFont(date_font)

        self._panel = _CalendarPopupPanel()
        self._calendar = self._panel.calendar()
        self._panel.datePicked.connect(self._on_calendar_picked)

        self._menu = QMenu(self)
        self._menu.setObjectName("LoginDateFieldMenu")
        menu_action = QWidgetAction(self._menu)
        menu_action.setDefaultWidget(self._panel)
        self._menu.addAction(menu_action)

        self._open_btn = QToolButton(self)
        self._open_btn.setObjectName("LoginFieldCalendar")
        _configure_icon_rail_button(
            self._open_btn,
            icon_name="fa5s.calendar-alt",
            tooltip="Open calendar",
            field_h=self._field_h,
            icon_size=_ICON_SIZE,
        )
        self._open_btn.clicked.connect(self._show_calendar)

        root.addWidget(self._date_edit, 1)
        root.addWidget(self._open_btn)

    def eventFilter(self, obj, event):
        if obj is self._date_edit:
            if event.type() == QEvent.Type.FocusIn:
                self.setProperty("focus", "true")
                self.style().unpolish(self)
                self.style().polish(self)
            elif event.type() == QEvent.Type.FocusOut:
                self.setProperty("focus", "false")
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(obj, event)

    def apply_theme(
        self,
        theme: dict,
        *,
        font_pt: int = 12,
        field_h: int | None = None,
        calendar_pt: int = 11,
        first_day_of_week: Qt.DayOfWeek = Qt.DayOfWeek.Saturday,
    ) -> None:
        t = theme or {}
        h = int(field_h if field_h is not None else self._field_h)
        self._field_h = h
        self.setFixedHeight(h)
        self._date_edit.setFixedHeight(max(28, h - 2))

        bg = t.get("panel_alt_bg", "#121a26")
        card = t.get("card_bg", "#162031")
        border = t.get("border", "#64748b")
        accent = t.get("accent", "#3b82f6")
        accent_soft = t.get("accent_soft", "#1e3a5f")
        text = t.get("text_primary", "#f8fafc")
        muted = t.get("text_muted", "#94a3b8")
        btn_text = t.get("button_text", "#ffffff")
        panel_bg = t.get("panel_bg", "#0f1419")

        _configure_icon_rail_button(
            self._open_btn,
            icon_name="fa5s.calendar-alt",
            tooltip="Open calendar",
            field_h=h,
            icon_color=btn_text,
        )

        self.setStyleSheet(f"""
            QWidget#LoginDateField {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                min-height: {h}px;
                max-height: {h}px;
            }}
            QWidget#LoginDateField:hover {{
                border: 1px solid {accent};
                background-color: {card};
            }}
            QWidget#LoginDateField[focus="true"] {{
                border: 1px solid {accent};
                background-color: {card};
            }}
            {_icon_rail_btn_qss(
                "QWidget#LoginDateField QToolButton#LoginFieldCalendar",
                border=border,
                accent_soft=accent_soft,
                accent=accent,
            )}
        """)
        self._date_edit.setStyleSheet(f"""
            QDateEdit {{
                background: transparent;
                border: none;
                color: {text};
                padding: 0 0 0 10px;
                font-size: {font_pt}pt;
                font-weight: 500;
                min-height: {max(26, h - 4)}px;
                max-height: {max(26, h - 4)}px;
                selection-background-color: {accent};
                selection-color: {btn_text};
            }}
            QDateEdit::drop-down {{ width: 0; height: 0; border: none; }}
            QDateEdit::down-arrow {{ width: 0; height: 0; image: none; border: none; }}
        """)
        self._menu.setStyleSheet(f"""
            QMenu {{
                background-color: {panel_bg};
                border: 1px solid {accent};
                border-radius: 10px;
                padding: 2px;
            }}
        """)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._panel.apply_theme(
            t,
            calendar_pt=calendar_pt,
            first_day_of_week=first_day_of_week,
        )

    def _show_calendar(self) -> None:
        self._panel.setSelectedDate(self._date_edit.date())
        anchor = self._open_btn.mapToGlobal(self._open_btn.rect().bottomRight())
        self._menu.popup(anchor)

    def _on_calendar_picked(self, picked: QDate) -> None:
        self._date_edit.setDate(picked)
        self._menu.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is not self._date_edit and not self._date_edit.isAncestorOf(child):
                self._show_calendar()
                event.accept()
                return
        super().mousePressEvent(event)

    def setToolTip(self, tip: str) -> None:  # noqa: N802 — Qt API
        super().setToolTip(tip)
        self._date_edit.setToolTip(tip)
        self._open_btn.setToolTip(tip or "Open calendar")

    def date(self) -> QDate:
        return self._date_edit.date()

    def setDate(self, date: QDate) -> None:  # noqa: N802 — Qt API
        self._date_edit.setDate(date)

    def setDisplayFormat(self, fmt: str) -> None:  # noqa: N802 — Qt API
        self._date_edit.setDisplayFormat(fmt)

    def calendarPopup(self) -> bool:
        return True

    def setCalendarPopup(self, enabled: bool) -> None:  # noqa: N802 — Qt API
        del enabled  # menu-based calendar is always available

    def calendarWidget(self) -> QCalendarWidget:
        return self._calendar

    def setCalendarWidget(self, widget: QCalendarWidget) -> None:  # noqa: N802
        if widget is self._calendar:
            return
        self._panel.replace_calendar(widget)
        self._calendar = widget


def login_form_fields_qss(*, scope: str = "") -> str:
    root = f"#{scope} " if scope else ""
    block = _LINE_EDIT_QSS.replace("QLineEdit", f"{root}QLineEdit")
    shell = _FIELD_SHELL_QSS
    if root:
        shell = shell.replace("QWidget#LoginNumberField", f"{root}QWidget#LoginNumberField")
        shell = shell.replace("QWidget#LoginComboField", f"{root}QWidget#LoginComboField")
        shell = shell.replace("QWidget#LoginDateField", f"{root}QWidget#LoginDateField")
        shell = shell.replace("QWidget#LoginLineField", f"{root}QWidget#LoginLineField")
    block += "\n" + shell
    return block


def configure_login_line_edit(field: QLineEdit) -> None:
    field.setFixedHeight(FIELD_H)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    field.setStyleSheet(_LINE_EDIT_QSS)


def configure_login_combobox(combo: QComboBox) -> None:
    combo.setFixedHeight(FIELD_H)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    combo.setStyleSheet(_COMBO_INNER_QSS + _COMBO_POPUP_QSS)


def configure_login_spinbox(spin: QSpinBox) -> None:
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setFixedHeight(FIELD_H)
    spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    spin.setStyleSheet(_LINE_EDIT_QSS)
