"""Title-bar user account dropdown (custom header, below window controls).

Always available — not gated on the Identity module flag. Opens a V2-styled
popup under the user pill with English copy.
"""

from __future__ import annotations

import logging

import qtawesome as qta
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


def _make_card_click_through(container: QWidget) -> None:
    """Route clicks on labels/icon to the card so the whole pill opens the menu."""
    try:
        for child in container.findChildren(QWidget):
            if child is container:
                continue
            if getattr(child, "_ino_badge", None) is not None:
                continue
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    except Exception as exc:
        logger.debug("user card click-through skipped: %s", exc)


def _menu_row(caption: str, icon_name: str, *, icon_color: str = "#60a5fa") -> QPushButton:
    btn = QPushButton(f"  {caption}")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(38)
    btn.setFlat(True)
    try:
        btn.setIcon(qta.icon(icon_name, color=icon_color))
    except Exception:
        pass
    try:
        from PacsClient.utils.v2_style import apply_dropdown_item_v2

        apply_dropdown_item_v2(btn)
    except Exception:
        btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 8px 12px; border: none; "
            "background: transparent; color: #e5e7eb; font-size: 13px; }"
            "QPushButton:hover { background: rgba(59,130,246,0.15); border-radius: 8px; }"
        )
    return btn


def attach_user_account_menu(
    user_container,
    *,
    auth_user=None,
    parent_window=None,
    control_panel=None,
):
    """Open the account dropdown when the title-bar user pill is clicked."""
    if getattr(user_container, "_user_account_menu_filter", None) is not None:
        return

    _make_card_click_through(user_container)
    user_container.setCursor(Qt.PointingHandCursor)
    user_container.setToolTip(user_container.toolTip() or "Open account menu")

    auth_user = auth_user or {}

    class _MenuFilter(QObject):
        def eventFilter(self, obj, event):
            try:
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    self._toggle()
            except Exception as exc:
                logger.debug("user account menu error: %s", exc)
            return False

        def _toggle(self):
            existing = getattr(user_container, "_user_account_popup", None)
            if existing is not None:
                try:
                    if existing.isVisible():
                        existing.close()
                        user_container._user_account_popup = None
                        return
                except Exception:
                    pass
            QTimer.singleShot(0, self._open)

        def _open(self):
            popup = _build_account_popup(
                user_container,
                auth_user=auth_user,
                parent_window=parent_window,
                control_panel=control_panel,
            )
            if popup is None:
                return
            popup.show()
            user_container._user_account_popup = popup

    flt = _MenuFilter(user_container)
    user_container.installEventFilter(flt)
    user_container._user_account_menu_filter = flt

    _attach_identity_extras(user_container, auth_user)


def _attach_identity_extras(user_container, auth_user) -> None:
    """Pill notification badge + consultation poller when Identity is enabled."""
    try:
        from modules.Identity.feature_flags import identity_module_enabled

        if not identity_module_enabled():
            return
        from modules.cloud_consultation.ui.account_hook import _attach_pill_badge
        from modules.cloud_consultation.notifications.autostart import (
            ensure_consultation_poller,
        )

        _attach_pill_badge(user_container, auth_user)
        ensure_consultation_poller(auth_user)
    except Exception as exc:
        logger.debug("identity extras on user pill skipped: %s", exc)


def _build_account_popup(anchor, *, auth_user, parent_window, control_panel):
    try:
        popup = QWidget(parent_window or anchor.window())
        popup.setObjectName("UserAccountMenuPopup")
        popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        popup.setAttribute(Qt.WA_DeleteOnClose, True)
        popup.setMinimumWidth(280)
        popup.setMaximumWidth(320)

        root = QVBoxLayout(popup)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(4)

        try:
            from PacsClient.utils.v2_style import apply_dropdown_panel_v2

            apply_dropdown_panel_v2(popup)
            # Panel QSS targets all QWidget children — strip accidental label borders.
            popup.setStyleSheet(
                popup.styleSheet()
                + """
            QWidget#UserAccountMenuPopup QLabel {
                border: none;
            }
            """
            )
        except Exception:
            popup.setStyleSheet(
                "QWidget { background: #111927; border: 1px solid #2d3748; border-radius: 12px; }"
            )

        header_cap = QLabel("ACCOUNT")
        try:
            from PacsClient.utils.v2_style import apply_dropdown_header_v2

            apply_dropdown_header_v2(header_cap)
        except Exception:
            header_cap.setStyleSheet("color: #93a4b7; font-size: 11px; font-weight: 700;")
        root.addWidget(header_cap)

        name = str(auth_user.get("full_name") or auth_user.get("username") or "User")
        role = str(auth_user.get("role") or "User").upper()
        identity = QFrame()
        identity.setObjectName("UserAccountIdentity")
        identity.setStyleSheet(
            "QFrame#UserAccountIdentity { background: transparent; border: none; }"
        )
        id_lay = QHBoxLayout(identity)
        id_lay.setContentsMargins(8, 4, 8, 10)
        id_lay.setSpacing(10)
        avatar = QLabel((name[:1] or "U").upper())
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "background: rgba(59,130,246,0.18); color: #60a5fa; border: 1px solid #3b82f6;"
            "border-radius: 18px; font-size: 14px; font-weight: 700;"
        )
        id_lay.addWidget(avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        nm = QLabel(name)
        nm.setStyleSheet(
            "color: #f8fafc; font-size: 13px; font-weight: 600;"
            "background: transparent; border: none;"
        )
        rl = QLabel(role)
        rl.setStyleSheet(
            "color: #93a4b7; font-size: 11px; background: transparent; border: none;"
        )
        col.addWidget(nm)
        col.addWidget(rl)
        id_lay.addLayout(col, 1)
        root.addWidget(identity)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #2d3748; border: none;")
        root.addWidget(sep)

        def _close():
            try:
                popup.close()
            except Exception:
                pass

        settings_btn = _menu_row("Settings", "fa5s.cog")
        settings_btn.clicked.connect(_close)
        settings_btn.clicked.connect(lambda: _open_settings(parent_window, control_panel))
        root.addWidget(settings_btn)

        notif_btn = _menu_row("Internal Assignments", "fa5s.bell", icon_color="#f59e0b")
        notif_btn.clicked.connect(_close)
        notif_btn.clicked.connect(lambda: _open_internal_notifications(anchor))
        root.addWidget(notif_btn)

        if _identity_available():
            accounts_btn = _menu_row("Connected Accounts", "fa5s.link", icon_color="#34d399")
            accounts_btn.clicked.connect(_close)
            accounts_btn.clicked.connect(
                lambda: _open_connected_accounts(auth_user, parent_window)
            )
            root.addWidget(accounts_btn)

        if _full_account_popup_available():
            more_btn = _menu_row("Account & Notifications", "fa5s.user-circle")
            more_btn.clicked.connect(_close)
            more_btn.clicked.connect(
                lambda: _open_full_account_popup(anchor, auth_user, parent_window)
            )
            root.addWidget(more_btn)

        hint = QLabel("Signed in to this workstation")
        hint.setStyleSheet("color: #64748b; font-size: 10px; padding: 8px 8px 2px 8px;")
        root.addWidget(hint)

        try:
            from PacsClient.utils.v2_style import position_dropdown_v2

            position_dropdown_v2(popup, anchor, gap_px=6)
        except Exception:
            g = anchor.mapToGlobal(anchor.rect().bottomRight())
            popup.adjustSize()
            popup.move(max(0, g.x() - popup.width()), g.y() + 6)

        popup.destroyed.connect(lambda *_: setattr(anchor, "_user_account_popup", None))
        return popup
    except Exception as exc:
        logger.warning("could not build user account menu: %s", exc)
        return None


def _identity_available() -> bool:
    try:
        from modules.Identity.feature_flags import identity_module_enabled

        return bool(identity_module_enabled())
    except Exception:
        return False


def _full_account_popup_available() -> bool:
    try:
        from modules.cloud_consultation.ui.account_popup import AccountPopup  # noqa: F401

        return _identity_available()
    except Exception:
        return False


def _open_settings(parent_window, control_panel) -> None:
    try:
        panel = control_panel
        if panel is None and parent_window is not None:
            panel = getattr(parent_window, "control_panel", None)
        if panel is None:
            return
        if hasattr(panel, "_show_settings_server_page"):
            panel._show_settings_server_page()
    except Exception as exc:
        logger.debug("open settings from account menu failed: %s", exc)


def _open_internal_notifications(anchor) -> None:
    try:
        from modules.network import ino_notifications

        ino_notifications.open_notifications_popup(anchor)
    except Exception as exc:
        logger.debug("open internal notifications failed: %s", exc)


def _open_connected_accounts(auth_user, parent_window) -> None:
    try:
        from modules.Identity.ui.account_menu_hook import _open_identity_panel

        _open_identity_panel(auth_user, parent_window)
    except Exception as exc:
        logger.debug("open connected accounts failed: %s", exc)


def _open_full_account_popup(anchor, auth_user, parent_window) -> None:
    try:
        from modules.cloud_consultation.ui.account_popup import AccountPopup

        popup = AccountPopup(auth_user=auth_user, parent=parent_window or anchor.window())
        popup.show_under(anchor)
        anchor._account_popup = popup
    except Exception as exc:
        logger.debug("open full account popup failed: %s", exc)
