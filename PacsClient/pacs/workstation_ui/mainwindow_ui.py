from PySide6.QtGui import Qt, QIcon, QCursor
from PySide6.QtWidgets import (
    QWidget, QApplication, QFrame, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QTabWidget,
    QAbstractButton, QLineEdit, QTextEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QAbstractSlider, QTabBar
)
from PySide6.QtCore import QEvent, QTimer

from .AIPacs_ui import ControlPanelInterface
from PacsClient.utils import IMAGES_LOGIN_PATH
from PacsClient.utils.db_manager import init_database, migrate_fix_null_study_paths
from PacsClient.utils.theme_manager import get_theme_manager
from .shortcut_manager import ShortcutManager
import qtawesome as qta
import sys
import logging
import os

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform == "linux"


class _PinnedHomeTabBar(QTabBar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._block_drag = False

    def mousePressEvent(self, event):
        self._block_drag = (self.tabAt(event.pos()) == 0)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._block_drag:
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._block_drag = False
        super().mouseReleaseEvent(event)

    def moveTab(self, from_index, to_index):
        if from_index == 0 or to_index == 0:
            return
        super().moveTab(from_index, to_index)

class MainWindowWidget(QWidget):
    _DEFAULT_STARTUP_IMPORT_DELAY_MS = 900

    def __init__(self, auth_user=None, auth_token=None, startup_import_folder: str | None = None):
        super().__init__()
        
        # ✅ Initialize database FIRST before any other initialization
        # This ensures api_token_usage and other tables exist before anything tries to access them
        init_database()
        migrate_fix_null_study_paths()
        
        self.setWindowIcon(QIcon(fr"{IMAGES_LOGIN_PATH}/favicon.ico"))
        self.setWindowFlags(Qt.FramelessWindowHint if IS_WINDOWS else Qt.Window)

        self.setMinimumSize(900, 520)

        self._normal_geometry = None
        self._was_maximized = False

        # ✅ flags برای SystemMove/SystemResize ویندوز
        self._in_system_move = False
        self._in_system_resize = False

        # ✅ جلوگیری از maximize مجدد وقتی از حالت maximized با drag برمی‌گردیم
        self._suppress_next_snap = False

        # --- titlebar drag gating (prevent single-click -> system move) ---
        self._pending_titlebar_move = False
        self._pending_titlebar_press_global = None  # QPoint
        self._pending_titlebar_press_local = None  # QPoint
        # Store authentication info
        self.auth_user = auth_user
        self.auth_token = auth_token
        self.startup_import_folder = startup_import_folder
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()

        self.setup_ui()
        self.window_buttons()
        if IS_WINDOWS:
            self._init_frameless_resize()

        self.setMouseTracking(True)

        # Initialize shortcut manager BEFORE adding AIPacs tab
        self.shortcut_manager = ShortcutManager(self)
        logger.info("Shortcut Manager initialized")

        # Now add AIPacs tab (which will connect to shortcut manager)
        self.add_AIPacs_tab()
        self._schedule_startup_import_if_requested()
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)

        # Register all long-lived resources with the lifecycle manager
        self._register_lifecycle_resources()

    def _schedule_startup_import_if_requested(self):
        """Schedule optional startup import if a folder was provided at launch."""
        folder = (self.startup_import_folder or "").strip()
        if not folder:
            return

        delay_ms = self._DEFAULT_STARTUP_IMPORT_DELAY_MS
        raw_delay = os.getenv("AIPACS_STARTUP_IMPORT_DELAY_MS", "").strip()
        if raw_delay:
            try:
                parsed = int(raw_delay)
                if parsed < 0:
                    raise ValueError("negative delay is invalid")
                delay_ms = parsed
            except Exception:
                logger.warning(
                    "[STARTUP] Invalid AIPACS_STARTUP_IMPORT_DELAY_MS=%r; using default %d ms",
                    raw_delay,
                    self._DEFAULT_STARTUP_IMPORT_DELAY_MS,
                )

        def _run_startup_import():
            try:
                home_widget = getattr(getattr(self, "control_panel", None), "home_widget", None)
                if not home_widget or not hasattr(home_widget, "auto_import_folder_from_startup"):
                    logger.warning("[STARTUP] Home widget import hook not available; skipping startup import")
                    return

                logger.info("[STARTUP] Auto-importing folder: %s", folder)
                home_widget.auto_import_folder_from_startup(folder)
            except Exception as exc:
                logger.warning("[STARTUP] Startup auto-import failed: %s", exc)

        # Give Qt time to render the main UI and initialize home panel state.
        QTimer.singleShot(delay_ms, _run_startup_import)

    def _arm_titlebar_move(self, global_pos, local_pos):
        """Arm a possible titlebar drag; we only start system move after real drag."""
        self._pending_titlebar_move = True
        self._pending_titlebar_press_global = global_pos
        self._pending_titlebar_press_local = local_pos

    def _cancel_titlebar_move(self):
        self._pending_titlebar_move = False
        self._pending_titlebar_press_global = None
        self._pending_titlebar_press_local = None

    def _start_native_system_move(self):
        if not IS_WINDOWS:
            return False
        wh = self.windowHandle()
        if not wh:
            return False
        self._moving = True
        self._in_system_move = True
        wh.startSystemMove()
        return True

    # ------------------------------------------------------------
    # ✅ ویندوز: تشخیص پایان حرکت/ریسایز native برای Snap-to-top
    # ------------------------------------------------------------
    def nativeEvent(self, eventType, message):
        if not IS_WINDOWS:
            return False, 0

        et = eventType if isinstance(eventType, str) else bytes(eventType).decode(errors="ignore")
        if "windows" not in et:
            return super().nativeEvent(eventType, message)

        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
        WM_EXITSIZEMOVE = 0x0232

        if msg.message == WM_EXITSIZEMOVE:
            # هر pending کلیک/درگ عنوان را پاک کن
            self._cancel_titlebar_move()

            if getattr(self, "_in_system_move", False):
                self._in_system_move = False

                # ✅ اگر تازه از maximized با drag برگشته‌ایم، این بار snap نکن
                if getattr(self, "_suppress_next_snap", False):
                    self._suppress_next_snap = False
                else:
                    # ✅ Snap-to-top فقط وقتی واقعاً system move شروع شده (با drag) رخ می‌دهد
                    QTimer.singleShot(0, self._maybe_snap_maximize)

            self._in_system_resize = False
            return False, 0

        return super().nativeEvent(eventType, message)

    def _init_frameless_resize(self):
        self._resize_margin = 10
        self._resizing = False
        self._moving = False

        self.setAttribute(Qt.WA_Hover, True)

        self._enable_mouse_tracking_recursive()
        self._install_global_frameless_event_filter()

        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar.setMouseTracking(True)
            self.title_bar.setAttribute(Qt.WA_Hover, True)

    def _screen_available_geometry(self):
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _maybe_snap_maximize(self):
        """
        Windows-like: اگر پنجره نزدیک لبه‌ی بالای screen رها شد => maximize
        """
        if self.isMaximized() or self.isMinimized() or (self.windowState() & Qt.WindowFullScreen):
            return

        avail = self._screen_available_geometry()
        if not avail:
            return

        geo = self.frameGeometry()
        snap_threshold = 8

        if geo.top() <= (avail.top() + snap_threshold):
            self.showMaximized()
            self._set_maximized_appearance(True)

            # برای Frameless: بعضی سیستم‌ها گپ میندازن => دقیقاً به availableGeometry بچسبون
            def _snap():
                avail2 = self._screen_available_geometry()
                if avail2:
                    self.setGeometry(avail2)

            QTimer.singleShot(10, _snap)
            self._sync_maximize_button_state()

    def _install_global_frameless_event_filter(self):
        app = QApplication.instance()
        if not app:
            return
        if getattr(self, "_frameless_filter_installed", False):
            return
        app.installEventFilter(self)
        self._frameless_filter_installed = True

    def _enable_mouse_tracking_recursive(self):
        self.setMouseTracking(True)
        for w in self.findChildren(QWidget):
            try:
                w.setMouseTracking(True)
            except Exception:
                pass

    def _is_interactive_child(self, w: QWidget) -> bool:
        return isinstance(
            w,
            (
                QAbstractButton, QLineEdit, QTextEdit, QPlainTextEdit,
                QComboBox, QSpinBox, QAbstractSlider, QTabBar
            )
        )

    # ------------------------------------------------------------
    # ✅ Restore-on-drag (مثل ویندوز) وقتی پنجره Maximized است
    # ------------------------------------------------------------
    def _restore_and_start_move_from_titlebar(self, global_pos):
        """
        Windows-like:
        وقتی maximized هست و کاربر titlebar را drag می‌کند => Restore و همان لحظه Move
        """
        avail = self._screen_available_geometry()
        if not avail:
            screen = self.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen else None
        if not avail:
            return

        normal = self._normal_geometry
        if normal is None:
            normal_w = max(self.minimumWidth(), 900)
            normal_h = max(self.minimumHeight(), 520)
        else:
            normal_w, normal_h = normal.width(), normal.height()

        # نسبت X موس روی پنجره (برای حفظ جای نسبی بعد از restore)
        fw = max(1, self.frameGeometry().width())
        x_ratio = (global_pos.x() - self.frameGeometry().left()) / fw
        x_ratio = max(0.0, min(1.0, x_ratio))

        # Restore
        self.showNormal()
        self._set_maximized_appearance(False)
        self._sync_maximize_button_state()

        # جلوگیری از snap دوباره در پایان همین حرکت
        self._suppress_next_snap = True

        new_x = int(global_pos.x() - x_ratio * normal_w)
        new_y = int(avail.top() + 4)

        new_x = max(avail.left(), min(new_x, avail.right() - normal_w + 1))
        new_y = max(avail.top(), min(new_y, avail.bottom() - normal_h + 1))

        self.setGeometry(new_x, new_y, normal_w, normal_h)

        # شروع حرکت native
        def _go():
            if IS_WINDOWS:
                wh = self.windowHandle()
                if wh:
                    self._moving = True
                    self._in_system_move = True
                    wh.startSystemMove()

        QTimer.singleShot(0, _go)

    def eventFilter(self, obj, event):
        # فقط رویدادهای مربوط به همین پنجره
        try:
            if not isinstance(obj, QWidget):
                return False
            if obj.window() is not self:
                return False
        except Exception:
            return False

        et = event.type()

        # global_pos را استاندارد استخراج کن
        if et in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            try:
                global_pos = event.globalPosition().toPoint()
            except Exception:
                global_pos = QCursor.pos()
        elif et == QEvent.HoverMove:
            global_pos = QCursor.pos()
        else:
            return False

        local_pos = self.mapFromGlobal(global_pos)

        # اگر maximized هستیم: فقط resize-cursor نده؛ ولی فیلتر را قطع نکن
        if self.isMaximized():
            if et in (QEvent.MouseMove, QEvent.HoverMove):
                self.unsetCursor()

        # اگر روی دکمه‌های پنجره هستیم، تداخل نکن
        if self._is_over_window_buttons(global_pos):
            if et in (QEvent.MouseMove, QEvent.HoverMove):
                self.unsetCursor()
            if et in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                self._cancel_titlebar_move()
            return False

        # --- 0) RELEASE: هر pending درگ را لغو کن ---
        if et == QEvent.MouseButtonRelease:
            self._cancel_titlebar_move()
            return False

        # --- 1) HOVER/MOVE (بدون دکمه): تغییر cursor روی لبه‌ها ---
        if et in (QEvent.MouseMove, QEvent.HoverMove):
            buttons = event.buttons() if hasattr(event, "buttons") else Qt.NoButton

            # اگر LeftDown و pending titlebar داریم، فقط در صورت عبور از threshold move را شروع کن
            if (buttons & Qt.LeftButton) and getattr(self, "_pending_titlebar_move", False):
                press_g = self._pending_titlebar_press_global
                if press_g is not None:
                    dx = abs(global_pos.x() - press_g.x())
                    dy = abs(global_pos.y() - press_g.y())
                    thresh = QApplication.startDragDistance() or 10

                    if (dx + dy) >= thresh:
                        self._cancel_titlebar_move()

                        if self.isMaximized():
                            self._restore_and_start_move_from_titlebar(global_pos)
                            return True

                        if self._start_native_system_move():
                            return True

            # اگر drag نداریم، فقط cursor لبه‌ها را بده
            if not (buttons & Qt.LeftButton):
                if not self.isMaximized():
                    edges = self._edges_at_pos(local_pos)
                    self.setCursor(self._cursor_for_edges(edges))

            return False

        # --- 2) PRESS ---
        if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # 2.1) Resize از لبه‌ها فقط در حالت normal
            if not self.isMaximized():
                edges = self._edges_at_pos(local_pos)
                if edges:
                    wh = self.windowHandle()
                    if wh:
                        self._resizing = True
                        self._in_system_resize = True
                        wh.startSystemResize(edges)
                        return True

            # 2.2) Titlebar press: فقط اگر واقعاً روی پس‌زمینه titlebar کلیک شده arm کن
            if self._is_titlebar_background_hit(global_pos, local_pos):
                self._arm_titlebar_move(global_pos, local_pos)
                return True

            # روی هر چیزی غیر از پس‌زمینه titlebar => رویداد را نخور
            return False

        # --- 3) Double click روی titlebar => maximize/restore (فقط وقتی background باشد) ---
        if et == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self._cancel_titlebar_move()

            if self._is_titlebar_background_hit(global_pos, local_pos):
                self._toggle_max_restore()
                return True

            return False

        return False

    def _is_over_window_buttons(self, global_pos) -> bool:
        for btn_name in ("minimize_button", "maximize_button", "close_button"):
            btn = getattr(self, btn_name, None)
            if btn and btn.isVisible():
                p = btn.mapFromGlobal(global_pos)
                if btn.rect().contains(p):
                    return True
        return False

    def _edges_at_pos(self, pos):
        m = self._resize_margin
        r = self.rect()

        x = pos.x()
        y = pos.y()

        left = x <= m
        right = x >= (r.width() - m)
        top = y <= m
        bottom = y >= (r.height() - m)

        edges = Qt.Edges()
        if left:
            edges |= Qt.Edge.LeftEdge
        if right:
            edges |= Qt.Edge.RightEdge
        if top:
            edges |= Qt.Edge.TopEdge
        if bottom:
            edges |= Qt.Edge.BottomEdge

        return edges if edges else None

    def _cursor_for_edges(self, edges):
        if not edges:
            return Qt.ArrowCursor

        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)

        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        if top or bottom:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    # ---------------- UI ----------------
    def setup_ui(self):
        self._main_layout = QVBoxLayout(self)
        main_layout = self._main_layout
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(0)

        self.setup_title_bar(main_layout)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabBar(_PinnedHomeTabBar())
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)

        try:
            self.tab_widget.tabBar().tabMoved.connect(self._ensure_home_tab_pinned)
        except Exception:
            pass

        # ✅ robust: هم از خود QTabWidget و هم QTabBar وصل کن
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        try:
            self.tab_widget.tabBar().tabCloseRequested.connect(self.close_tab)
        except Exception:
            pass

        main_layout.addWidget(self.tab_widget)

        self.apply_modern_styling()

    def _is_titlebar_background_hit(self, global_pos, local_pos) -> bool:
        """
        فقط وقتی True بده که کلیک دقیقاً روی خودِ TitleBar (پس‌زمینه) باشد،
        نه روی هیچ child (مثل tab_area، tab buttons، close button، labels، ...).
        """
        if not hasattr(self, "title_bar") or not self.title_bar:
            return False

        # داخل محدوده عنوان؟
        if not self.title_bar.geometry().contains(local_pos):
            return False

        # روی دکمه‌های پنجره نباشد
        if self._is_over_window_buttons(global_pos):
            return False

        # روی tabbar استاندارد هم نباشد
        if self._is_over_tabbar(global_pos):
            return False

        # مهم: اگر widget زیر موس چیزی غیر از خود title_bar باشد => یعنی روی یک child هستیم
        w = QApplication.widgetAt(global_pos)
        if w is None:
            return False

        return (w is self.title_bar)

    def _is_over_tabbar(self, global_pos) -> bool:
        """True اگر موس روی ناحیه QTabBar استاندارد QTabWidget باشد."""
        try:
            if not hasattr(self, "tab_widget") or self.tab_widget is None:
                return False
            tb = self.tab_widget.tabBar()
            if tb is None or not tb.isVisible():
                return False
            p = tb.mapFromGlobal(global_pos)
            return tb.rect().contains(p)
        except Exception:
            return False

    def setup_title_bar(self, parent_layout):
        self.title_bar = QFrame()
        self.title_bar.setObjectName("TitleBar")
        self.title_bar.setFixedHeight(84)

        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 2, 5, 2)
        title_layout.setSpacing(10)

        self.tab_area = QFrame()
        self.tab_area.setObjectName("TabArea")
        title_layout.addWidget(self.tab_area)

        title_layout.addStretch()

        # Right-side tab area (next to admin/user info)
        self.right_tab_area = QFrame()
        self.right_tab_area.setObjectName("RightTabArea")
        title_layout.addWidget(self.right_tab_area)

        if self.auth_user:
            self.setup_user_info(title_layout)

        parent_layout.addWidget(self.title_bar)

    def setup_user_info(self, title_layout):
        user_container = QFrame()
        user_container.setObjectName("UserInfoContainer")
        self.user_info_container = user_container
        user_container.setFixedHeight(70)
        user_container.setMinimumWidth(170)
        user_container.setStyleSheet("""
            QFrame#UserInfoContainer {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(59, 130, 246, 0.22),
                    stop:1 rgba(99, 102, 241, 0.18));
                border: 2px solid rgba(99, 102, 241, 0.4);
                border-radius: 10px;
                padding: 6px 14px;
                margin-right: 10px;
            }
            QFrame#UserInfoContainer:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(59, 130, 246, 0.34),
                    stop:1 rgba(99, 102, 241, 0.28));
                border: 2px solid rgba(148, 163, 184, 0.7);
            }
            QLabel#UserNameLabel {
                color: #ffffff;
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.3px;
                background: transparent;
                border: none;
            }
            QLabel#UserRoleLabel {
                color: #93c5fd;
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 0.5px;
                background: transparent;
                border: none;
            }
        """)

        lay = QHBoxLayout(user_container)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)

        user_icon_label = QLabel()
        user_icon = qta.icon('fa5s.user', color='#60a5fa')
        user_icon_label.setPixmap(user_icon.pixmap(36, 36))
        user_icon_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(user_icon_label)

        text_lay = QVBoxLayout()
        text_lay.setSpacing(2)
        text_lay.setContentsMargins(0, 2, 0, 2)

        user_name = self.auth_user.get('full_name', 'Unknown User')
        if len(user_name) > 20:
            user_name = user_name[:17] + "..."
        self.user_name_label = QLabel(user_name)
        self.user_name_label.setObjectName("UserNameLabel")
        text_lay.addWidget(self.user_name_label)

        user_role = self.auth_user.get('role', 'User').upper()
        self.user_role_label = QLabel(f"● {user_role}")
        self.user_role_label.setObjectName("UserRoleLabel")
        text_lay.addWidget(self.user_role_label)

        lay.addLayout(text_lay)

        title_layout.addWidget(user_container)

    def get_tab_area(self):
        return self.tab_area

    def get_right_tab_area(self):
        return self.right_tab_area

    def apply_modern_styling(self):
        theme = getattr(self, "_active_theme", None) or get_theme_manager().current_theme()
        self.setStyleSheet(
            f"""
            MainWindowWidget {{
                background: {theme['window_bg']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
            }}
            QFrame#TitleBar {{
                background: {theme['menu_bg']};
                border: none;
                border-bottom: 1px solid {theme['border']};
            }}
            QFrame#TabArea {{ background: transparent; border: none; }}
            QFrame#RightTabArea {{ background: transparent; border: none; }}

            QTabWidget {{ background: transparent; border: none; }}
            QTabWidget::pane {{ border: none; background: {theme['window_bg']}; }}

            QTabBar::tab {{
                background: {theme['tab_bg']};
                color: {theme['text_muted']};
                border: 1px solid {theme['border']};
                border-bottom: none;
                border-radius: 4px 4px 0px 0px;
                padding: 6px 12px;
                margin-right: 1px;
                font-size: 11px;
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background: {theme['tab_active_bg']};
                color: {theme['button_text']};
                border-color: {theme['tab_active_bg']};
            }}
            QTabBar::tab:hover:!selected {{
                background: {theme['tab_hover_bg']};
                color: {theme['text_primary']};
            }}
            QTabBar::close-button {{
                background: rgba(239, 68, 68, 0.7);
                border-radius: 8px;
                width: 14px;
                height: 14px;
                margin: 2px;
            }}
            QTabBar::close-button:hover {{ background: rgba(239, 68, 68, 1.0); }}

            MainWindowWidget[maximized="true"] {{
                border: none;
                border-radius: 0px;
            }}
            MainWindowWidget[maximized="true"] QFrame#TitleBar {{
                border-radius: 0px;
            }}
            """
        )

    def _user_info_stylesheet(self) -> str:
        theme = self._active_theme
        return f"""
            QFrame#UserInfoContainer {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {theme['accent_soft']},
                    stop:1 {theme['menu_bg']});
                border: 2px solid {theme['accent']};
                border-radius: 10px;
                padding: 6px 14px;
                margin-right: 10px;
            }}
            QFrame#UserInfoContainer:hover {{
                border-color: {theme['accent_hover']};
            }}
            QLabel#UserNameLabel {{
                color: {theme['text_primary']};
                font-size: 13px;
                font-weight: 700;
                letter-spacing: 0.3px;
                background: transparent;
                border: none;
            }}
            QLabel#UserRoleLabel {{
                color: {theme['text_secondary']};
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 0.5px;
                background: transparent;
                border: none;
            }}
        """

    def _window_button_styles(self) -> dict[str, str]:
        theme = self._active_theme
        neutral = f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme['menu_bg']}, stop:1 {theme['panel_bg']});
                border: 1px solid {theme['border']};
                border-radius: 5px;
                color: {theme['text_primary']};
                font-size: 16px;
                font-weight: normal;
            }}
            QPushButton:hover {{
                background: {theme['menu_hover_bg']};
                border: 1px solid {theme['accent']};
            }}
            QPushButton:pressed {{
                background: {theme['panel_deep_bg']};
                border: 1px solid {theme['accent_pressed']};
            }}
        """
        close = f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {theme['border']};
                border-radius: 4px;
                color: {theme['text_primary']};
                font-size: 16px;
                font-weight: normal;
            }}
            QPushButton:hover {{
                background: {theme['danger']};
                border: 1px solid {theme['danger']};
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background: {theme['danger_hover']};
                border: 1px solid {theme['danger_hover']};
            }}
        """
        return {"neutral": neutral, "close": close}

    def apply_theme(self, theme=None):
        self._active_theme = theme or self.theme_manager.current_theme()
        self.apply_modern_styling()
        if hasattr(self, "user_info_container"):
            self.user_info_container.setStyleSheet(self._user_info_stylesheet())
        styles = self._window_button_styles()
        if hasattr(self, "minimize_button"):
            self.minimize_button.setStyleSheet(styles["neutral"])
        if hasattr(self, "maximize_button"):
            self.maximize_button.setStyleSheet(styles["neutral"])
        if hasattr(self, "close_button"):
            self.close_button.setStyleSheet(styles["close"])

    def _set_maximized_appearance(self, is_max: bool):
        self.setProperty("maximized", "true" if is_max else "false")

        if hasattr(self, "_main_layout") and self._main_layout:
            m = 0 if is_max else 2
            self._main_layout.setContentsMargins(m, m, m, m)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _find_home_tab_index(self) -> int:
        """
        Home tab را پیدا می‌کند.
        پیش‌فرض شما Home همان تب AI PACS است.
        اگر پیدا نشد، 0 برمی‌گرداند.
        """
        try:
            if not hasattr(self, "tab_widget") or self.tab_widget is None:
                return 0

            for i in range(self.tab_widget.count()):
                t = (self.tab_widget.tabText(i) or "").strip().lower()
                if "ai pacs" in t or "home" in t:
                    return i
        except Exception:
            pass

        return 0

    def _ensure_home_tab_pinned(self, *_args) -> None:
        if getattr(self, "_pinning_home_tab", False):
            return
        if not hasattr(self, "tab_widget") or self.tab_widget is None:
            return
        if self.tab_widget.count() == 0:
            return

        home_i = self._find_home_tab_index()
        if 0 <= home_i < self.tab_widget.count() and home_i != 0:
            self._pinning_home_tab = True
            try:
                self.tab_widget.tabBar().moveTab(home_i, 0)
            finally:
                self._pinning_home_tab = False

    def _go_home_tab(self) -> None:
        """همیشه به Home برگرد."""
        try:
            if not hasattr(self, "tab_widget") or self.tab_widget is None:
                return
            home_i = self._find_home_tab_index()
            if 0 <= home_i < self.tab_widget.count():
                self.tab_widget.setCurrentIndex(home_i)
        except Exception:
            pass

    # ---------------- Tabs ----------------
    def close_tab(self, index: int):
        if not hasattr(self, "tab_widget"):
            return

        home_i = self._find_home_tab_index()
        if index == home_i:
            return

        widget = self.tab_widget.widget(index)
        if not widget:
            return

        # Determine which tab to select after closing
        # If closing the current tab, select the previous tab (or home if none)
        current_i = self.tab_widget.currentIndex()
        should_go_home = (current_i == index)

        self.tab_widget.removeTab(index)

        if should_go_home:
            # If we closed the current tab, go to home or previous tab
            if self.tab_widget.count() > 1:
                # There are other tabs besides home, select the previous one
                new_index = min(index, self.tab_widget.count() - 1)
                if new_index != home_i:
                    self.tab_widget.setCurrentIndex(new_index)
                else:
                    self.tab_widget.setCurrentIndex(home_i)
            else:
                # Only home tab remains
                self.tab_widget.setCurrentIndex(home_i)
        # If we closed a background tab, keep current selection unchanged

        def _cleanup():
            try:
                if hasattr(widget, "exit_patient_widget"):
                    widget.exit_patient_widget()
            finally:
                widget.setParent(None)
                widget.deleteLater()

        delay = 50 if IS_MAC else 0
        QTimer.singleShot(delay, _cleanup)

    def _is_in_tabbar_chain(self, w: QWidget) -> bool:
        """True اگر widget مقصد (obj) خودش یا یکی از والدها QTabBar باشد."""
        while w is not None:
            if isinstance(w, QTabBar):
                return True
            w = w.parentWidget()
        return False

    def add_AIPacs_tab(self):
        if hasattr(self, "control_panel"):
            return  # دوباره ساخته نشود

        self.control_panel = ControlPanelInterface(tab_widget=self.tab_widget, host_window=self)

        if hasattr(self, 'shortcut_manager'):
            self.shortcut_manager.set_control_panel(self.control_panel)
            logger.info("Shortcut Manager connected to Control Panel")

        # Only set mouse tracking on the newly added control_panel subtree.
        # _init_frameless_resize() already processed the pre-existing widgets;
        # re-scanning the entire tree would be O(all_widgets) redundant work.
        if IS_WINDOWS:
            self.control_panel.setMouseTracking(True)
            for w in self.control_panel.findChildren(QWidget):
                try:
                    w.setMouseTracking(True)
                except Exception:
                    pass
        self._ensure_home_tab_pinned()

    # ---------------- Window buttons ----------------
    def window_buttons(self):
        # Minimize Button - Windows 10 Style with visible border
        self.minimize_button = QPushButton("─")
        self.minimize_button.setObjectName("MinimizeButton")
        self.minimize_button.setToolTip("Minimize")
        self.minimize_button.setFixedSize(46, 32)
        self.minimize_button.setStyleSheet("""
            QPushButton#MinimizeButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(30, 41, 59, 0.25), stop:1 rgba(15, 23, 42, 0.25));
                border: 1px solid rgba(148, 163, 184, 0.45);
                border-radius: 5px;
                color: #ffffff;
                font-size: 16px;
                font-weight: normal;
            }
            QPushButton#MinimizeButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(59, 130, 246, 0.18), stop:1 rgba(15, 23, 42, 0.2));
                border: 1px solid rgba(226, 232, 240, 0.7);
                color: #ffffff;
            }
            QPushButton#MinimizeButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(15, 23, 42, 0.6), stop:1 rgba(2, 6, 23, 0.7));
                border: 1px solid rgba(148, 163, 184, 0.6);
            }
        """)
        self.minimize_button.clicked.connect(self.showMinimized)

        # Maximize/Restore Button - Windows 10 Style with visible border
        self.maximize_button = QPushButton("□")
        self.maximize_button.setObjectName("MaximizeButton")
        self.maximize_button.setToolTip("Maximize")
        self.maximize_button.setFixedSize(46, 32)
        self.maximize_button.setStyleSheet("""
            QPushButton#MaximizeButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(30, 41, 59, 0.25), stop:1 rgba(15, 23, 42, 0.25));
                border: 1px solid rgba(148, 163, 184, 0.45);
                border-radius: 5px;
                color: #ffffff;
                font-size: 16px;
                font-weight: normal;
            }
            QPushButton#MaximizeButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(59, 130, 246, 0.18), stop:1 rgba(15, 23, 42, 0.2));
                border: 1px solid rgba(226, 232, 240, 0.7);
                color: #ffffff;
            }
            QPushButton#MaximizeButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(15, 23, 42, 0.6), stop:1 rgba(2, 6, 23, 0.7));
                border: 1px solid rgba(148, 163, 184, 0.6);
            }
        """)
        self.maximize_button.clicked.connect(self._toggle_max_restore)

        # Close Button - Windows 10 Style (Red on hover) with visible border
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("CloseButton")
        self.close_button.setToolTip("Close")
        self.close_button.setFixedSize(46, 32)
        self.close_button.setStyleSheet("""
            QPushButton#CloseButton {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                color: #ffffff;
                font-size: 16px;
                font-weight: normal;
            }
            QPushButton#CloseButton:hover {
                background: #e81123;
                border: 1px solid #e81123;
                color: #ffffff;
            }
            QPushButton#CloseButton:pressed {
                background: rgba(232, 17, 35, 0.8);
                border: 1px solid rgba(232, 17, 35, 0.8);
            }
        """)
        self.close_button.clicked.connect(self.close)

        title_layout = self.title_bar.layout()
        title_layout.addWidget(self.minimize_button)
        title_layout.addWidget(self.maximize_button)
        title_layout.addWidget(self.close_button)

        self._sync_maximize_button_state()

    def _toggle_max_restore(self):
        if not self.isMaximized():
            self._normal_geometry = self.geometry()

            self.showMaximized()
            self._set_maximized_appearance(True)

            def _snap():
                screen = self.screen() or QApplication.primaryScreen()
                if screen:
                    self.setGeometry(screen.availableGeometry())

            QTimer.singleShot(10, _snap)
        else:
            self.showNormal()
            self._set_maximized_appearance(False)
            if self._normal_geometry is not None:
                QTimer.singleShot(0, lambda: self.setGeometry(self._normal_geometry))

        self._sync_maximize_button_state()

    def _sync_maximize_button_state(self):
        if getattr(self, "maximize_button", None) is None:
            return
        if self.isMaximized():
            self.maximize_button.setText("❐")
            self.maximize_button.setToolTip("Restore Down")
        else:
            self.maximize_button.setText("□")
            self.maximize_button.setToolTip("Maximize")

    def _is_tab_interaction_at(self, global_pos) -> bool:
        """تشخیص اینکه موقعیت موس روی تب‌ها/close-button هست یا نه."""
        w = QApplication.widgetAt(global_pos)
        return self._is_in_tabbar_chain(w) if w else False

    # ---------------- State tracking ----------------
    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            is_max = self.isMaximized()
            self._set_maximized_appearance(is_max)
            self._sync_maximize_button_state()
        super().changeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if (not self.isMaximized()) and (not self.isMinimized()) and (not (self.windowState() & Qt.WindowFullScreen)):
            self._normal_geometry = self.geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        if (not self.isMaximized()) and (not self.isMinimized()) and (not (self.windowState() & Qt.WindowFullScreen)):
            self._normal_geometry = self.geometry()

    def closeEvent(self, event):
        # Drain all registered resources in reverse order via lifecycle manager.
        from PacsClient.components.lifecycle_manager import lifecycle_manager
        results = lifecycle_manager.shutdown_all()
        for name, err in results.items():
            if err is not None:
                logger.warning("shutdown(%s) warning: %s", name, err)
        # Break reference cycles that the GC can't collect (VTK C++ pointers etc.)
        # A single explicit gc.collect() before the process ends silences the
        # "gc: N uncollectable objects at shutdown" ResourceWarning.
        import gc
        gc.collect()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    # ------------------------------------------------------------------
    # Lifecycle resource registration
    # ------------------------------------------------------------------
    def _register_lifecycle_resources(self):
        """Register long-lived subsystem shutdown callbacks.

        Called once at the end of __init__, after all widgets are created.
        The lifecycle manager drains resources in LIFO order, so
        register dependencies (DB, cache infra) first and consumers
        (thread pools, socket) last.
        """
        from PacsClient.components.lifecycle_manager import lifecycle_manager

        # 1. Database connection pool (lowest-level dependency)
        def _shutdown_db():
            from database.core import cleanup_connection_pools
            cleanup_connection_pools()

        lifecycle_manager.register("database.connection_pools", _shutdown_db, timeout=5.0)

        # 2. Cache cleanup threads
        def _shutdown_caches():
            from PacsClient.pacs.patient_tab.utils.cache import (
                _thumbnail_cache, _metadata_cache, _image_cache,
            )
            from PacsClient.pacs.patient_tab.utils.utils import clear_study_cache
            from modules.viewer.fast.disk_pixel_cache import get_disk_pixel_cache
            for cache in (_thumbnail_cache, _metadata_cache, _image_cache):
                if cache is None:
                    continue
                if hasattr(cache, 'stop_auto_cleanup'):
                    cache.stop_auto_cleanup()
                if hasattr(cache, 'clear'):
                    cache.clear()
            clear_study_cache()
            get_disk_pixel_cache().clear()

        lifecycle_manager.register("cache.auto_cleanup_threads", _shutdown_caches, timeout=3.0)

        # 3. HomePanelWidget thread pool + background tasks
        def _shutdown_home():
            if hasattr(self, 'control_panel') and hasattr(self.control_panel, 'home_widget'):
                hw = self.control_panel.home_widget
                if hasattr(hw, 'cleanup'):
                    hw.cleanup()

        lifecycle_manager.register("HomePanelWidget.cleanup", _shutdown_home, timeout=5.0)

        # 4. Close all open patient tabs (ZetaBoost engines, VTK resources)
        def _shutdown_patient_tabs():
            if not hasattr(self, 'tab_widget'):
                return
            home_i = self._find_home_tab_index()
            for i in range(self.tab_widget.count() - 1, -1, -1):
                if i == home_i:
                    continue
                w = self.tab_widget.widget(i)
                if w and hasattr(w, 'exit_patient_widget'):
                    try:
                        w.exit_patient_widget()
                    except Exception as exc:
                        logger.warning("exit_patient_widget warning tab %s: %s", i, exc)

        lifecycle_manager.register("patient_tabs.exit_all", _shutdown_patient_tabs, timeout=10.0)

        # 5. Download Manager widget / worker pool teardown
        def _shutdown_download_manager():
            from modules.download_manager.ui.main_widget import DownloadManagerWidget

            if hasattr(self, 'control_panel') and hasattr(self.control_panel, 'home_widget'):
                hw = self.control_panel.home_widget
                if hasattr(hw, 'download_service') and hw.download_service is not None:
                    try:
                        hw.download_service.cleanup()
                    except Exception as exc:
                        logger.warning("download_service.cleanup warning: %s", exc)

            if not hasattr(self, 'tab_widget'):
                return
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget) and hasattr(widget, 'cleanup'):
                    try:
                        widget.cleanup()
                    except Exception as exc:
                        logger.warning("DownloadManagerWidget.cleanup warning tab %s: %s", i, exc)

        lifecycle_manager.register("download_manager.cleanup", _shutdown_download_manager, timeout=10.0)

        # 6. Socket service (highest-level – shuts down last)
        def _shutdown_socket():
            from modules.network.socket_service import get_socket_service
            socket_service = get_socket_service()
            socket_service.cleanup()

        lifecycle_manager.register("socket_service", _shutdown_socket, timeout=5.0)
