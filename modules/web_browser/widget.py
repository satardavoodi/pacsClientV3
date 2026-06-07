"""
Web Browser Widget for AIPacs
A compact web browser with integrated download manager
"""

from PySide6.QtCore import *
from PySide6.QtWidgets import *
from PySide6.QtWebEngineWidgets import *
from PySide6.QtWebEngineCore import *
from PySide6.QtGui import *
import os
from datetime import datetime
from pathlib import Path
import qtawesome as qta
import base64
from urllib.parse import quote_plus

from PacsClient.utils.data_paths import (
    BROWSER_SAVED_PAGES_DIR,
    BROWSER_SCREENSHOTS_DIR,
)
from PacsClient.utils.theme_manager import get_theme_manager
from .state_store import BrowserStateStore
from .styles import (
    RADIUS_CONTROL,
    RADIUS_GROUP,
    RADIUS_PANEL,
    RADIUS_PILL,
    card_qss,
    dialog_button_qss,
    icon_button_qss,
    input_qss,
    popup_panel_qss,
    progress_qss,
    section_button_qss,
    shell_qss,
    state_button_qss,
    tool_button_qss,
)


HOME_URL = "https://www.google.com"


def _current_theme():
    return get_theme_manager().current_theme()


def apply_shadow(widget, blur=24, y_offset=6, alpha=70):
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setXOffset(0)
    shadow.setYOffset(y_offset)
    shadow.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(shadow)


class BookmarkDialog(QDialog):
    """Dialog for adding/editing a bookmark"""
    
    def __init__(self, parent=None, bookmark_data=None):
        super().__init__(parent)
        self._theme = _current_theme()
        self.bookmark_data = bookmark_data
        self.setWindowTitle("Add Favorite" if not bookmark_data else "Edit Favorite")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setup_ui()
        
        if bookmark_data:
            self.load_bookmark_data()
    
    def setup_ui(self):
        t = self._theme
        self.setStyleSheet(f"QDialog {{ background-color: {t['panel_bg']}; }}")
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Favorite Details")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {t['text_primary']};")
        layout.addWidget(title)
        
        # Form layout
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        
        # Style for labels
        label_style = f"color: {t['text_primary']}; font-size: 13px; font-weight: bold;"
        # One shared field style (was 4 duplicated — and brace-broken — blocks
        # whose f-strings raised NameError and killed this dialog; 2026-06-07).
        field_style = input_qss(t)

        # Name field
        name_label = QLabel("Name:")
        name_label.setStyleSheet(label_style)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., STATdx")
        self.name_edit.setMinimumHeight(40)
        self.name_edit.setStyleSheet(field_style)

        # URL field
        url_label = QLabel("URL:")
        url_label.setStyleSheet(label_style)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        self.url_edit.setMinimumHeight(40)
        self.url_edit.setStyleSheet(field_style)

        # Username field
        username_label = QLabel("Username:")
        username_label.setStyleSheet(label_style)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username (optional)")
        self.username_edit.setMinimumHeight(40)
        self.username_edit.setStyleSheet(field_style)

        # Password field
        password_label = QLabel("Password:")
        password_label.setStyleSheet(label_style)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Password (optional)")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(40)
        self.password_edit.setStyleSheet(field_style)
        
        # Show password checkbox
        self.show_password_cb = QCheckBox("Show Password")
        self.show_password_cb.stateChanged.connect(self.toggle_password_visibility)
        self.show_password_cb.setStyleSheet(f"color: {t['text_secondary']}; font-size: 13px;")
        
        form_layout.addRow(name_label, self.name_edit)
        form_layout.addRow(url_label, self.url_edit)
        form_layout.addRow(username_label, self.username_edit)
        form_layout.addRow(password_label, self.password_edit)
        form_layout.addRow("", self.show_password_cb)
        
        layout.addLayout(form_layout)
        
        # Note
        note = QLabel("Note: Credentials are stored locally and encoded.")
        note.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px; font-style: italic;")
        layout.addWidget(note)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setMinimumHeight(45)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(dialog_button_qss(t, primary=False))

        save_btn = QPushButton("Save")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(45)
        save_btn.clicked.connect(self.accept)
        save_btn.setStyleSheet(dialog_button_qss(t, primary=True))
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def toggle_password_visibility(self, state):
        if state == Qt.Checked:
            self.password_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
    
    def load_bookmark_data(self):
        if self.bookmark_data:
            self.name_edit.setText(self.bookmark_data.get('name', ''))
            self.url_edit.setText(self.bookmark_data.get('url', ''))
            self.username_edit.setText(self.bookmark_data.get('username', ''))
            # Decode password
            encoded_pass = self.bookmark_data.get('password', '')
            if encoded_pass:
                try:
                    password = base64.b64decode(encoded_pass).decode('utf-8')
                    self.password_edit.setText(password)
                except:
                    pass
    
    def get_bookmark_data(self):
        password = self.password_edit.text()
        # Encode password
        encoded_pass = base64.b64encode(password.encode('utf-8')).decode('utf-8') if password else ''
        
        return {
            'name': self.name_edit.text(),
            'url': self.url_edit.text(),
            'username': self.username_edit.text(),
            'password': encoded_pass,
            'timestamp': datetime.now().isoformat()
        }


class ScreenshotDialog(QDialog):
    """Dialog for naming and configuring a browser screenshot."""

    def __init__(self, parent=None, default_name="web_capture"):
        super().__init__(parent)
        self._theme = _current_theme()
        self.setWindowTitle("Capture Screenshot")
        self.setMinimumWidth(420)
        self.default_name = default_name
        self.setup_ui()

    def setup_ui(self):
        t = self._theme
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {t['panel_bg']}; }}
            QLabel {{ color: {t['text_primary']}; }}
            {input_qss(t)}
            """
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Browser Screenshot")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_edit = QLineEdit(self.default_name)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Visible page only", "web_view")
        self.mode_combo.addItem("Full browser panel", "browser")

        form.addRow("File name", self.name_edit)
        form.addRow("Capture area", self.mode_combo)
        layout.addLayout(form)

        note = QLabel("Screenshots are stored inside user_data/web_browser/screenshots.")
        note.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet(dialog_button_qss(t, primary=False))
        capture_btn = QPushButton("Capture")
        capture_btn.clicked.connect(self.accept)
        capture_btn.setStyleSheet(dialog_button_qss(t, primary=True))
        buttons.addWidget(cancel_btn)
        buttons.addWidget(capture_btn)
        layout.addLayout(buttons)

    def payload(self):
        return {
            "name": self.name_edit.text().strip() or self.default_name,
            "mode": self.mode_combo.currentData(),
        }


class BookmarkItemWidget(QFrame):
    """Widget for displaying a single bookmark"""
    
    clicked = Signal(str)  # Emits URL
    edited = Signal(dict)  # Emits bookmark data
    deleted = Signal(str)  # Emits bookmark ID
    
    def __init__(self, bookmark_id, bookmark_data, parent=None):
        super().__init__(parent)
        self.bookmark_id = bookmark_id
        self.bookmark_data = bookmark_data
        self.setup_ui()
    
    def setup_ui(self):
        t = _current_theme()
        self.setFrameStyle(QFrame.NoFrame)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Check if has credentials
        has_credentials = bool(self.bookmark_data.get('username') or self.bookmark_data.get('password'))

        # Name with icon
        name_text = self.bookmark_data.get('name', 'Unnamed')
        if has_credentials:
            name_text = "🔐 " + name_text

        name_label = QLabel(name_text)
        name_label.setStyleSheet(f"font-size: 13px; color: {t['text_primary']}; padding: 4px; background: transparent; border: none;")
        name_label.setWordWrap(False)

        # Minimal icon buttons (shared module style)
        button_style = icon_button_qss(t)

        # Visit button
        visit_btn = QPushButton()
        visit_btn.setIcon(qta.icon('fa5s.external-link-alt', color=t['text_muted']))
        visit_btn.setFixedSize(24, 24)
        visit_btn.setToolTip("Visit")
        visit_btn.clicked.connect(lambda: self.clicked.emit(self.bookmark_data.get('url', '')))
        visit_btn.setStyleSheet(button_style)

        # Auto-login button (if credentials exist)
        login_btn = None
        if has_credentials:
            login_btn = QPushButton()
            login_btn.setIcon(qta.icon('fa5s.sign-in-alt', color=t['success']))
            login_btn.setFixedSize(24, 24)
            login_btn.setToolTip("Auto-fill")
            login_btn.clicked.connect(self.auto_login)
            login_btn.setStyleSheet(button_style)

        # Edit button
        edit_btn = QPushButton()
        edit_btn.setIcon(qta.icon('fa5s.edit', color=t['text_muted']))
        edit_btn.setFixedSize(24, 24)
        edit_btn.setToolTip("Edit")
        edit_btn.clicked.connect(self.edit_bookmark)
        edit_btn.setStyleSheet(button_style)

        # Delete button
        delete_btn = QPushButton()
        delete_btn.setIcon(qta.icon('fa5s.trash', color=t['text_muted']))
        delete_btn.setFixedSize(24, 24)
        delete_btn.setToolTip("Delete")
        delete_btn.clicked.connect(lambda: self.deleted.emit(self.bookmark_id))
        delete_btn.setStyleSheet(button_style)

        # Add to layout
        layout.addWidget(name_label, 1)
        layout.addWidget(visit_btn)
        if login_btn:
            layout.addWidget(login_btn)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)

        # Minimal style with no border
        self.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
                border: none;
                border-radius: {RADIUS_CONTROL}px;
            }}
            QFrame:hover {{
                background-color: {t['menu_hover_bg']};
            }}
        """)
    
    def auto_login(self):
        # Emit URL to navigate
        self.clicked.emit(self.bookmark_data.get('url', ''))
        
        # Show credentials in a message box for user to manually enter
        # (Auto-fill in web pages is complex and may not work with all sites)
        username = self.bookmark_data.get('username', '')
        password = self.bookmark_data.get('password', '')
        
        if password:
            try:
                password = base64.b64decode(password).decode('utf-8')
            except:
                pass
        
        # Themed via the app-wide QMessageBox stylesheet; only the rich-text
        # body needs token colors here.
        t = _current_theme()
        msg = QMessageBox(self)
        msg.setWindowTitle("Login Credentials")
        msg.setIcon(QMessageBox.Information)

        msg_text = f"""
        <div style='color: {t['text_primary']};'>
        <p style='font-size: 15px; margin-bottom: 15px;'><b>Website:</b> <span style='color: {t['accent']};'>{self.bookmark_data.get('name', 'Unknown')}</span></p>
        <p style='font-size: 14px; margin-bottom: 10px;'><b>Username:</b> <span style='color: {t['success']};'>{username}</span></p>
        <p style='font-size: 14px; margin-bottom: 15px;'><b>Password:</b> <span style='color: {t['success']};'>{password}</span></p>
        <p style='font-size: 12px; color: {t['text_muted']}; font-style: italic;'>Please enter these credentials on the website.</p>
        </div>
        """
        msg.setText(msg_text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()
    
    def edit_bookmark(self):
        dialog = BookmarkDialog(self, self.bookmark_data)
        if dialog.exec() == QDialog.Accepted:
            updated_data = dialog.get_bookmark_data()
            self.edited.emit({'id': self.bookmark_id, 'data': updated_data})


class BookmarkPanel(QWidget):
    """Favorites manager panel."""

    bookmark_clicked = Signal(str)

    def __init__(self, state_store, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.bookmarks = self.state_store.load_favorites()
        self.setup_ui()
        self.reload_bookmarks()

    def setup_ui(self):
        self.setObjectName("BrowserBookmarkPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

        self.header = QWidget()
        self.header.setFixedHeight(42)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 0, 12, 0)

        self.title_label = QLabel("Favorites")

        self.add_btn = QPushButton()
        self.add_btn.setFixedSize(28, 28)
        self.add_btn.setToolTip("Add Favorite")
        self.add_btn.clicked.connect(self.add_bookmark)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.add_btn)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.bookmarks_widget = QWidget()
        self.bookmarks_layout = QVBoxLayout(self.bookmarks_widget)
        self.bookmarks_layout.setAlignment(Qt.AlignTop)
        self.bookmarks_layout.setSpacing(2)
        self.bookmarks_layout.setContentsMargins(8, 8, 8, 8)
        self.scroll_area.setWidget(self.bookmarks_widget)

        self.empty_label = QLabel("No favorites yet")
        self.empty_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.header)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.empty_label)
        self.apply_theme()
        self.update_empty_state()

    def apply_theme(self, theme=None):
        t = theme or _current_theme()
        self.setStyleSheet(popup_panel_qss(t, "BrowserBookmarkPanel"))
        self.header.setStyleSheet(
            f"background-color: {t['panel_bg']}; border: none; border-bottom: 1px solid {t['border']};"
        )
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; background: transparent; border: none;"
        )
        self.add_btn.setIcon(qta.icon("fa5s.plus", color=t['accent']))
        self.add_btn.setStyleSheet(icon_button_qss(t))
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {t['panel_bg']}; }}"
        )
        self.bookmarks_widget.setStyleSheet(
            f"background-color: {t['panel_bg']}; border: none;"
        )
        self.empty_label.setStyleSheet(
            f"color: {t['text_muted']}; font-size: 13px; padding: 40px; background: transparent; border: none;"
        )

    def add_bookmark(self, current_url=None, current_title=None):
        dialog = BookmarkDialog(self)
        if current_url:
            dialog.url_edit.setText(current_url)
        if current_title:
            dialog.name_edit.setText(current_title)

        if dialog.exec() == QDialog.Accepted:
            bookmark_data = dialog.get_bookmark_data()
            bookmark_id = str(datetime.now().timestamp())
            self.bookmarks[bookmark_id] = bookmark_data
            self.save_bookmarks()
            self.reload_bookmarks()

    def create_bookmark_widget(self, bookmark_id, bookmark_data):
        bookmark_item = BookmarkItemWidget(bookmark_id, bookmark_data)
        bookmark_item.clicked.connect(self.bookmark_clicked.emit)
        bookmark_item.edited.connect(self.edit_bookmark)
        bookmark_item.deleted.connect(self.delete_bookmark)
        self.bookmarks_layout.addWidget(bookmark_item)
        return bookmark_item

    def edit_bookmark(self, data):
        bookmark_id = data["id"]
        bookmark_data = data["data"]
        if bookmark_id in self.bookmarks:
            self.bookmarks[bookmark_id] = bookmark_data
            self.save_bookmarks()
            self.reload_bookmarks()

    def delete_bookmark(self, bookmark_id):
        reply = QMessageBox.question(
            self,
            "Delete Favorite",
            "Are you sure you want to delete this favorite?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes and bookmark_id in self.bookmarks:
            del self.bookmarks[bookmark_id]
            self.save_bookmarks()
            self.reload_bookmarks()

    def reload_bookmarks(self):
        for i in reversed(range(self.bookmarks_layout.count())):
            widget = self.bookmarks_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        for bookmark_id, bookmark_data in self.bookmarks.items():
            self.create_bookmark_widget(bookmark_id, bookmark_data)
        self.update_empty_state()

    def update_empty_state(self):
        has_bookmarks = len(self.bookmarks) > 0
        self.scroll_area.setVisible(has_bookmarks)
        self.empty_label.setVisible(not has_bookmarks)

    def save_bookmarks(self):
        self.state_store.save_favorites(self.bookmarks)


class HistoryPanel(QWidget):
    """Persistent browsing history panel."""

    history_clicked = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("BrowserHistoryPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("History")
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.clear_btn)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter history")
        self.search_edit.textChanged.connect(self.refresh_list)

        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(self._open_item)
        self.list_widget.itemDoubleClicked.connect(self._open_item)

        self.empty_label = QLabel("No pages visited yet")
        self.empty_label.setAlignment(Qt.AlignCenter)

        layout.addLayout(header_layout)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.empty_label)
        self.apply_theme()
        self.update_empty_state()

    def apply_theme(self, theme=None):
        t = theme or _current_theme()
        self.setStyleSheet(popup_panel_qss(t, "BrowserHistoryPanel"))
        self.title_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {t['text_primary']}; background: transparent; border: none;"
        )
        self.clear_btn.setStyleSheet(dialog_button_qss(t, primary=False))
        self.search_edit.setStyleSheet(input_qss(t))
        self.empty_label.setStyleSheet(
            f"color: {t['text_muted']}; padding: 30px; background: transparent; border: none;"
        )

    def set_entries(self, entries):
        self.entries = list(entries)
        self.refresh_list()

    def refresh_list(self):
        needle = self.search_edit.text().strip().lower()
        self.list_widget.clear()
        for entry in self.entries:
            title = entry.get("title") or entry.get("url", "Untitled")
            url = entry.get("url", "")
            if needle and needle not in f"{title} {url}".lower():
                continue
            visited_at = entry.get("visited_at", "")
            text = f"{title}\n{url}\nVisited: {visited_at[:16].replace('T', ' ')}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, url)
            self.list_widget.addItem(item)
        self.update_empty_state()

    def update_empty_state(self):
        has_items = self.list_widget.count() > 0
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)

    def _open_item(self, item):
        url = item.data(Qt.UserRole)
        if url:
            self.history_clicked.emit(url)


class SavedItemCardWidget(QFrame):
    """Compact card widget for a saved browser item."""

    def __init__(self, entry, max_width=240, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.max_width = max_width
        self.setup_ui()

    def setup_ui(self):
        t = _current_theme()
        self.setStyleSheet(card_qss(t))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        item_type = self.entry.get("item_type", "download")
        icon_name = {
            "page": "fa5s.file-code",
            "screenshot": "fa5s.camera",
            "download": "fa5s.download",
        }.get(item_type, "fa5s.file")
        icon_color = {
            "page": t['info'],
            "screenshot": t['warning'],
            "download": t['success'],
        }.get(item_type, t['text_secondary'])

        icon_holder = QLabel()
        icon_holder.setFixedSize(26, 26)
        icon_holder.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(18, 18))
        icon_holder.setAlignment(Qt.AlignCenter)
        icon_holder.setStyleSheet(
            f"background-color: {t['panel_alt_bg']}; border: 1px solid {t['border']}; border-radius: {RADIUS_CONTROL}px;"
        )
        layout.addWidget(icon_holder, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = self.entry.get("title") or Path(self.entry.get("path", "")).name or "Saved item"
        path = self.entry.get("path", "")
        created_at = self.entry.get("created_at", "")[:16].replace("T", " ")

        metrics = self.fontMetrics()
        text_width = max(150, min(self.max_width, metrics.horizontalAdvance(title) + 22))
        path_text = metrics.elidedText(path, Qt.TextElideMode.ElideMiddle, text_width)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"font-weight: 700; color: {t['text_primary']};")
        self.title_label.setMaximumWidth(text_width)

        self.path_label = QLabel(path_text)
        self.path_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px;")
        self.path_label.setMaximumWidth(text_width)

        self.time_label = QLabel(f"Saved: {created_at}")
        self.time_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        self.time_label.setMaximumWidth(text_width)

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.path_label)
        text_layout.addWidget(self.time_label)
        layout.addLayout(text_layout)

        self.adjustSize()
        desired_width = min(self.max_width + 56, max(text_width + 60, 190))
        self.setFixedWidth(desired_width)


class SavedItemsSidebar(QWidget):
    """Sidebar showing saved pages, screenshots, and downloads."""

    item_activated = Signal(dict)
    reveal_requested = Signal(dict)
    screenshot_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self._collapsed = False
        self.active_filter = "all"
        self.expanded_width = 310
        self.collapsed_width = 86
        self.setup_ui()

    def setup_ui(self):
        self.setObjectName("BrowserSavedSidebar")
        self.setMinimumWidth(self.expanded_width)
        self.setMaximumWidth(self.expanded_width)
        apply_shadow(self, blur=28, y_offset=10, alpha=55)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.header_layout = QHBoxLayout()
        self.icon_badge = QLabel()
        self.icon_badge.setFixedSize(34, 34)
        self.icon_badge.setAlignment(Qt.AlignCenter)
        self.title = QLabel("Saved Browser Items")
        self.count_badge = QLabel("0")
        self.count_badge.setAlignment(Qt.AlignCenter)
        self.count_badge.setFixedHeight(24)
        self.count_badge.setMinimumWidth(28)
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.clicked.connect(self.toggle_collapsed)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)
        self.header_layout.addWidget(self.icon_badge)
        self.header_layout.addWidget(self.title, 1)
        self.header_layout.addWidget(self.count_badge)
        self.header_layout.addWidget(self.toggle_btn)
        layout.addLayout(self.header_layout)

        self.details_widget = QWidget()
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(10)

        self.hero_card = QFrame()
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(6)
        self.hero_title = QLabel("Library")
        self.summary_label = QLabel("Pages, screenshots, videos, and other downloaded content")
        self.summary_label.setWordWrap(True)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.summary_label)
        details_layout.addWidget(self.hero_card)

        self.options_shell = QFrame()
        options_layout = QVBoxLayout(self.options_shell)
        options_layout.setContentsMargins(10, 10, 10, 10)
        options_layout.setSpacing(8)
        self.options_label = QLabel("Sections")
        options_layout.addWidget(self.options_label)

        self.section_grid = QGridLayout()
        self.section_grid.setContentsMargins(0, 0, 0, 0)
        self.section_grid.setHorizontalSpacing(8)
        self.section_grid.setVerticalSpacing(8)
        self.section_buttons = {}

        section_specs = [
            ("all", "All Item", "fa5s.layer-group", False),
            ("page", "Save Image", "fa5s.image", False),
            ("screenshot", "Screenshot", "fa5s.camera", True),
            ("download", "Downloads", "fa5s.download", False),
        ]
        for index, (section_key, label, icon_name, triggers_capture) in enumerate(section_specs):
            button = self._make_section_button(label, icon_name)
            if triggers_capture:
                button.clicked.connect(
                    lambda _checked=False, key=section_key: self._on_screenshot_section_clicked(key)
                )
            else:
                button.clicked.connect(
                    lambda _checked=False, key=section_key: self.set_active_filter(key)
                )
            self.section_buttons[section_key] = button
            self.section_grid.addWidget(button, index // 2, index % 2)
        options_layout.addLayout(self.section_grid)
        details_layout.addWidget(self.options_shell)

        self.library_panel = QFrame()
        library_layout = QVBoxLayout(self.library_panel)
        library_layout.setContentsMargins(10, 10, 10, 10)
        library_layout.setSpacing(8)
        self.library_label = QLabel("Library")
        library_layout.addWidget(self.library_label)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setIconSize(QSize(18, 18))
        self.list_widget.setSpacing(2)
        self.list_widget.itemActivated.connect(self._emit_item)
        self.list_widget.itemDoubleClicked.connect(self._emit_item)
        library_layout.addWidget(self.list_widget, 1)

        self.controls_shell = QFrame()
        controls = QHBoxLayout(self.controls_shell)
        controls.setContentsMargins(10, 10, 10, 10)
        controls.setSpacing(8)
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_current)
        self.folder_btn = QPushButton("Folder")
        self.folder_btn.clicked.connect(self.reveal_current)
        controls.addWidget(self.open_btn)
        controls.addWidget(self.folder_btn)

        self.empty_label = QLabel("No saved browser items yet")
        self.empty_label.setAlignment(Qt.AlignCenter)
        library_layout.addWidget(self.empty_label)
        details_layout.addWidget(self.library_panel, 1)
        details_layout.addWidget(self.controls_shell)
        layout.addWidget(self.details_widget, 1)
        self.apply_theme()
        self.set_collapsed(False)
        self.set_active_filter("all")
        self.update_empty_state()

    def apply_theme(self, theme=None):
        t = theme or _current_theme()
        self._theme = t
        self.setStyleSheet(
            f"""
            QWidget#BrowserSavedSidebar {{
                background-color: {t['panel_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: {RADIUS_PANEL}px;
            }}
            QLabel {{ color: {t['text_primary']}; background: transparent; border: none; }}
            QListWidget {{
                background-color: {t['panel_deep_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: {RADIUS_GROUP}px;
                padding: 6px;
                outline: none;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 2px 0 4px 0;
                margin: 0px;
            }}
            QListWidget::item:selected, QListWidget::item:hover {{
                background: transparent;
                border: none;
            }}
            """
        )
        self.icon_badge.setPixmap(qta.icon("fa5s.folder-open", color=t['accent']).pixmap(18, 18))
        self.icon_badge.setStyleSheet(
            f"background-color: {t['panel_alt_bg']}; border: 1px solid {t['border']}; border-radius: {RADIUS_CONTROL}px;"
        )
        self.title.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent; border: none;")
        self.count_badge.setStyleSheet(
            f"background-color: {t['accent']}; color: {t['button_text']}; border: none;"
            " border-radius: 12px; font-weight: 700; padding: 0 8px;"
        )
        self.toggle_btn.setStyleSheet(tool_button_qss(t))
        self.hero_card.setStyleSheet(
            f"""
            QFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {t['panel_alt_bg']}, stop:1 {t['accent_soft']});
                border: 1px solid {t['border']};
                border-radius: {RADIUS_GROUP}px;
            }}
            """
        )
        self.hero_title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {t['text_primary']};")
        self.summary_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px;")
        self.options_shell.setStyleSheet(shell_qss(t))
        self.options_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px; font-weight: 600;")
        section_style = section_button_qss(t)
        for button in self.section_buttons.values():
            button.setStyleSheet(section_style)
        self.library_panel.setStyleSheet(shell_qss(t))
        self.library_label.setStyleSheet(f"color: {t['text_primary']}; font-size: 12px; font-weight: 700;")
        self.controls_shell.setStyleSheet(shell_qss(t))
        self.open_btn.setStyleSheet(dialog_button_qss(t, primary=True))
        self.folder_btn.setStyleSheet(dialog_button_qss(t, primary=False))
        self.empty_label.setStyleSheet(
            f"color: {t['text_muted']}; padding: 28px; background-color: {t['panel_deep_bg']};"
            f" border: 1px dashed {t['border']}; border-radius: {RADIUS_GROUP}px;"
        )
        # Re-tint the collapse chevron for the current theme/state.
        icon_name = "fa5s.chevron-right" if self._collapsed else "fa5s.chevron-left"
        self.toggle_btn.setIcon(qta.icon(icon_name, color=t['text_primary']))

    def set_items(self, items):
        self.items = list(items)
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        self.count_badge.setText(str(len(self.items)))
        filter_value = self.active_filter
        available_width = max(180, self.expanded_width - 56)
        for entry in self.items:
            item_type = entry.get("item_type", "download")
            if filter_value != "all" and item_type != filter_value:
                continue
            card = SavedItemCardWidget(entry, max_width=available_width)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, entry)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
        self.update_empty_state()

    def update_empty_state(self):
        has_items = self.list_widget.count() > 0
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)

    def current_entry(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def open_current(self):
        entry = self.current_entry()
        if entry:
            self.item_activated.emit(entry)

    def reveal_current(self):
        entry = self.current_entry()
        if entry:
            self.reveal_requested.emit(entry)

    def _emit_item(self, item):
        entry = item.data(Qt.UserRole)
        if entry:
            self.item_activated.emit(entry)

    def _make_section_button(self, label, icon_name):
        t = _current_theme()
        button = QPushButton(label)
        button.setCheckable(True)
        button.setMinimumHeight(54)
        button.setIcon(qta.icon(icon_name, color=t['text_secondary']))
        button.setIconSize(QSize(16, 16))
        button.setStyleSheet(section_button_qss(t))
        return button

    def set_active_filter(self, filter_name):
        self.active_filter = filter_name
        for key, button in self.section_buttons.items():
            button.setChecked(key == filter_name)
        self.refresh_list()

    def _on_screenshot_section_clicked(self, filter_name):
        self.set_active_filter(filter_name)
        self.screenshot_requested.emit()

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        self.details_widget.setVisible(not self._collapsed)
        self.title.setVisible(not self._collapsed)
        self.count_badge.setVisible(not self._collapsed)
        if self._collapsed:
            self.header_layout.setSpacing(4)
            self.icon_badge.setFixedSize(28, 28)
            self.toggle_btn.setFixedSize(24, 24)
        else:
            self.header_layout.setSpacing(8)
            self.icon_badge.setFixedSize(34, 34)
            self.toggle_btn.setFixedSize(28, 28)
        width = self.collapsed_width if self._collapsed else self.expanded_width
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        icon_name = "fa5s.chevron-right" if self._collapsed else "fa5s.chevron-left"
        tooltip = "Expand sidebar" if self._collapsed else "Collapse sidebar"
        t = getattr(self, "_theme", None) or _current_theme()
        self.toggle_btn.setIcon(qta.icon(icon_name, color=t['text_primary']))
        self.toggle_btn.setToolTip(tooltip)


class DownloadItemWidget(QFrame):
    """Widget for displaying a single download"""
    
    canceled = Signal(str)
    paused = Signal(str)
    resumed = Signal(str)
    
    def __init__(self, download_id, filename, url, save_path, parent=None, download_request=None):
        super().__init__(parent)
        self.download_id = download_id
        self.filename = filename
        self.url = url
        self.save_path = save_path
        self.download_request = download_request
        self.start_time = datetime.now()
        self.is_paused = False
        self.is_completed = False
        self.is_canceled = False
        
        self.setup_ui()
        
    def setup_ui(self):
        t = _current_theme()
        self._t = t
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Top row: Icon, filename, controls
        top_layout = QHBoxLayout()

        # Icon
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.file', color=t['accent']).pixmap(28, 28))
        icon_label.setFixedSize(32, 32)

        # Filename
        self.name_label = QLabel(self.filename)
        self.name_label.setStyleSheet(f"font-weight: bold; font-size: 12px; color: {t['text_primary']};")
        self.name_label.setWordWrap(False)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # Control buttons (semantic states: pause=warning, cancel=danger,
        # open=success — token-driven, shared hover/pressed/disabled rules)
        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(qta.icon('fa5s.pause', color=t['button_text']))
        self.pause_btn.setFixedSize(32, 32)
        self.pause_btn.setToolTip("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setStyleSheet(state_button_qss(t, "warning"))

        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(qta.icon('fa5s.times', color=t['button_text']))
        self.cancel_btn.setFixedSize(32, 32)
        self.cancel_btn.setToolTip("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setStyleSheet(state_button_qss(t, "danger"))

        self.open_btn = QPushButton()
        self.open_btn.setIcon(qta.icon('fa5s.folder-open', color=t['button_text']))
        self.open_btn.setFixedSize(32, 32)
        self.open_btn.setToolTip("Open File")
        self.open_btn.clicked.connect(self.open_file)
        self.open_btn.hide()
        self.open_btn.setStyleSheet(state_button_qss(t, "success"))

        top_layout.addWidget(icon_label)
        top_layout.addWidget(self.name_label, 1)
        top_layout.addWidget(self.pause_btn)
        top_layout.addWidget(self.cancel_btn)
        top_layout.addWidget(self.open_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setStyleSheet(progress_qss(t, "accent"))

        # Status labels
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Starting download...")
        self.status_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        self.speed_label.setAlignment(Qt.AlignRight)

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.speed_label)

        # Add to main layout
        layout.addLayout(top_layout)
        layout.addWidget(self.progress_bar)
        layout.addLayout(status_layout)

        self.setStyleSheet(card_qss(t))
        if self.download_request is None:
            self.pause_btn.hide()
            self.cancel_btn.hide()
        
    def toggle_pause(self):
        if self.download_request is None:
            return
        if not self.is_paused:
            self.is_paused = True
            self.download_request.pause()
            self.pause_btn.setIcon(qta.icon('fa5s.play', color='white'))
            self.pause_btn.setToolTip("Resume")
            self.status_label.setText("Paused")
            self.paused.emit(self.download_id)
        else:
            self.is_paused = False
            self.download_request.resume()
            self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
            self.pause_btn.setToolTip("Pause")
            self.status_label.setText("Downloading...")
            self.resumed.emit(self.download_id)
            
    def cancel_download(self):
        if self.download_request is not None:
            self.download_request.cancel()
        self.is_canceled = True
        self.status_label.setText("Canceled")
        self.progress_bar.setStyleSheet(progress_qss(self._t, "danger"))
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.canceled.emit(self.download_id)
        
    def update_progress(self, received, total):
        if total > 0:
            progress = int((received / total) * 100)
            self.progress_bar.setValue(progress)
            
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed > 0:
                speed = received / elapsed
                speed_text = self.format_size(speed) + "/s"
                
                if speed > 0:
                    remaining = (total - received) / speed
                    remaining_text = self.format_time(remaining)
                    self.speed_label.setText(f"{speed_text} - {remaining_text} left")
                else:
                    self.speed_label.setText(speed_text)
            
            self.status_label.setText(f"{self.format_size(received)} of {self.format_size(total)}")
            
    def set_completed(self):
        self.is_completed = True
        self.is_paused = False
        self.progress_bar.setValue(100)
        self.progress_bar.setStyleSheet(progress_qss(self._t, "success"))
        self.status_label.setText("Download completed")
        self.speed_label.setText("")
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.open_btn.show()
        
    def set_error(self, error_msg):
        self.status_label.setText(f"Error: {error_msg}")
        self.progress_bar.setStyleSheet(progress_qss(self._t, "danger"))
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        
    def open_file(self):
        if os.path.exists(self.save_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.save_path))
    
    @staticmethod
    def format_size(size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
    
    @staticmethod
    def format_time(seconds):
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"


class DownloadManagerPanel(QWidget):
    """Download Manager Panel"""
    
    def __init__(self, state_store, parent=None):
        super().__init__(parent)
        self.state_store = state_store
        self.downloads = {}
        self.download_history = self.state_store.load_download_history()
        self.setup_ui()
        self.load_history()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self.header = QWidget()
        self.header.setFixedHeight(50)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(15, 0, 15, 0)

        self.title_label = QLabel("Downloads")

        self.clear_btn = QPushButton()
        self.clear_btn.setText("Clear Completed")
        self.clear_btn.clicked.connect(self.clear_completed)

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.clear_btn)

        # Downloads area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.downloads_widget = QWidget()
        self.downloads_layout = QVBoxLayout(self.downloads_widget)
        self.downloads_layout.setAlignment(Qt.AlignTop)
        self.downloads_layout.setSpacing(10)
        self.downloads_layout.setContentsMargins(15, 15, 15, 15)

        self.scroll_area.setWidget(self.downloads_widget)

        # Empty state
        self.empty_label = QLabel("No downloads yet")
        self.empty_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.header)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.empty_label)

        self.apply_theme()
        self.update_empty_state()

    def apply_theme(self, theme=None):
        t = theme or _current_theme()
        self.header.setStyleSheet(
            f"background-color: {t['panel_bg']}; border: none; border-bottom: 1px solid {t['border']};"
        )
        self.title_label.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {t['text_primary']}; background: transparent; border: none;"
        )
        self.clear_btn.setIcon(qta.icon('fa5s.trash', color=t['text_primary']))
        self.clear_btn.setStyleSheet(dialog_button_qss(t, primary=False))
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {t['panel_deep_bg']}; }}"
        )
        self.downloads_widget.setStyleSheet(
            f"background-color: {t['panel_deep_bg']}; border: none;"
        )
        self.empty_label.setStyleSheet(
            f"color: {t['text_muted']}; font-size: 14px; padding: 50px; background: transparent; border: none;"
        )
        
    def add_download(self, download_id, filename, url, save_path, download_request=None):
        download_item = DownloadItemWidget(
            download_id,
            filename,
            url,
            save_path,
            download_request=download_request,
        )
        self.downloads[download_id] = download_item
        self.downloads_layout.addWidget(download_item)
        self.update_empty_state()
        return download_item
        
    def remove_download(self, download_id):
        if download_id in self.downloads:
            item = self.downloads[download_id]
            self.downloads_layout.removeWidget(item)
            item.deleteLater()
            del self.downloads[download_id]
            self.update_empty_state()
            
    def clear_completed(self):
        to_remove = []
        for download_id, item in self.downloads.items():
            if item.is_completed or item.is_canceled:
                to_remove.append(download_id)
        for download_id in to_remove:
            self.remove_download(download_id)
            
    def update_empty_state(self):
        has_downloads = len(self.downloads) > 0
        self.scroll_area.setVisible(has_downloads)
        self.empty_label.setVisible(not has_downloads)
        
    def save_history(self):
        self.state_store.save_download_history(self.download_history)
            
    def load_history(self):
        self.download_history = self.state_store.load_download_history()


class WebBrowserWidget(QWidget):
    """Main Web Browser Widget for AIPacs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        self.state_store = BrowserStateStore()
        self.page_history = self.state_store.load_page_history()
        self.saved_pages = self.state_store.load_saved_pages()
        self.saved_items = self.state_store.load_saved_items()
        self.current_title = ""
        self._is_loading = False
        self._url_user_editing = False
        self.downloads_path = str(self.state_store.downloads_dir)
        self.screenshots_path = str(self.state_store.screenshots_dir)
        os.makedirs(self.downloads_path, exist_ok=True)
        os.makedirs(self.screenshots_path, exist_ok=True)
        
        self.setup_ui()
        self.setup_profile()
        self._apply_theme_styles()

    def _on_theme_changed(self, theme):
        self._theme = theme or self.theme_manager.current_theme()
        self._apply_theme_styles()

    def _apply_theme_styles(self):
        """Single source of truth for the browser chrome styling.

        Radius scale (see .styles): panels 12 / groups 10 / controls 8 /
        address pill 16. Icons are re-tinted here so they stay readable on
        every theme (they were hard-coded dark gray before).
        """
        t = self._theme
        if hasattr(self, "nav_bar"):
            self.nav_bar.setStyleSheet(
                f"""
                QWidget {{
                    background: {t['panel_bg']};
                    border: 1px solid {t['border']};
                    border-radius: {RADIUS_PANEL}px;
                }}
                """
            )

        button_style = tool_button_qss(t)
        icon_color = t['text_primary']
        toolbar_icons = [
            ("back_btn", "fa5s.arrow-left"),
            ("forward_btn", "fa5s.arrow-right"),
            ("home_btn", "fa5s.home"),
            ("history_btn", "fa5s.history"),
            ("bookmark_btn", "fa5s.bookmark"),
            ("save_page_btn", "fa5s.save"),
            ("downloads_toggle", "fa5s.download"),
            ("screenshot_btn", "fa5s.camera"),
        ]
        for attr, icon_name in toolbar_icons:
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setStyleSheet(button_style)
                btn.setIcon(qta.icon(icon_name, color=icon_color))
        if hasattr(self, "reload_btn"):
            self.reload_btn.setStyleSheet(button_style)
            self._update_reload_button_icon()
        if hasattr(self, "favorite_toggle_btn"):
            self.favorite_toggle_btn.setStyleSheet(button_style)
            self.update_favorite_button()

        group_style = (
            f"QFrame {{ background-color: {t['panel_bg']}; border: 1px solid {t['border']};"
            f" border-radius: {RADIUS_GROUP}px; }}"
        )
        if hasattr(self, "left_group"):
            self.left_group.setStyleSheet(group_style)
        if hasattr(self, "right_group"):
            self.right_group.setStyleSheet(group_style)
        if hasattr(self, "address_group"):
            self._style_address_group(focused=self.url_bar.hasFocus() if hasattr(self, "url_bar") else False)
        if hasattr(self, "address_icon"):
            self.address_icon.setPixmap(qta.icon("fa5s.globe", color=t['text_muted']).pixmap(16, 16))

        if hasattr(self, "url_bar"):
            # The address GROUP is the single visible pill; the line edit is
            # transparent inside it (no more box-in-a-box double border).
            self.url_bar.setStyleSheet(
                f"""
                QLineEdit {{
                    padding: 10px 6px;
                    border: none;
                    background: transparent;
                    font-size: 13px;
                    color: {t['text_primary']};
                    selection-background-color: {t['accent']};
                }}
                """
            )

        if hasattr(self, "content_row"):
            self.content_row.setStyleSheet(
                f"QWidget {{ background: {t['window_alt_bg']}; border-radius: {RADIUS_PANEL}px; }}"
            )

        if hasattr(self, "page_frame"):
            self.page_frame.setStyleSheet(
                f"QFrame {{ background-color: {t['panel_bg']}; border: 1px solid {t['border']};"
                f" border-radius: {RADIUS_PANEL}px; }}"
            )

        if hasattr(self, "progress_bar"):
            self.progress_bar.setStyleSheet(
                f"""
                QProgressBar {{
                    border: none;
                    background-color: {t['panel_alt_bg']};
                }}
                QProgressBar::chunk {{
                    background-color: {t['accent']};
                }}
                """
            )

        # Retint the side panels / popups so a live theme switch reaches them.
        for panel_attr in ("saved_items_sidebar", "bookmark_panel", "history_panel", "download_panel"):
            panel = getattr(self, panel_attr, None)
            if panel is not None and hasattr(panel, "apply_theme"):
                panel.apply_theme(t)

    def _style_address_group(self, focused=False):
        t = self._theme
        border_color = t['accent'] if focused else t['border']
        self.address_group.setStyleSheet(
            f"QFrame {{ background-color: {t['panel_deep_bg']}; border: 1px solid {border_color};"
            f" border-radius: {RADIUS_PILL}px; }}"
        )

    def _update_reload_button_icon(self):
        """Reload button doubles as Stop while a page is loading."""
        t = self._theme
        if getattr(self, "_is_loading", False):
            self.reload_btn.setIcon(qta.icon('fa5s.times', color=t['danger']))
            self.reload_btn.setToolTip("Stop loading")
        else:
            self.reload_btn.setIcon(qta.icon('fa5s.sync', color=t['text_primary']))
            self.reload_btn.setToolTip("Reload")
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Splitter for browser and downloads
        self.splitter = QSplitter(Qt.Vertical)
        
        # Browser section
        browser_container = QWidget()
        browser_layout = QVBoxLayout(browser_container)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(0)
        
        # Navigation bar (all styling lives in _apply_theme_styles —
        # the single theme-token source; nothing is styled inline here)
        nav_bar = QWidget()
        self.nav_bar = nav_bar
        nav_bar.setFixedHeight(72)
        apply_shadow(nav_bar, blur=26, y_offset=8, alpha=45)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(12, 10, 12, 10)
        nav_layout.setSpacing(10)

        # Navigation buttons
        self.back_btn = QPushButton()
        self.back_btn.setFixedSize(36, 36)
        self.back_btn.setToolTip("Back")
        self.back_btn.clicked.connect(self.navigate_back)

        self.forward_btn = QPushButton()
        self.forward_btn.setFixedSize(36, 36)
        self.forward_btn.setToolTip("Forward")
        self.forward_btn.clicked.connect(self.navigate_forward)

        self.reload_btn = QPushButton()
        self.reload_btn.setFixedSize(36, 36)
        self.reload_btn.setToolTip("Reload")
        self.reload_btn.clicked.connect(self.reload_page)

        self.home_btn = QPushButton()
        self.home_btn.setFixedSize(36, 36)
        self.home_btn.setToolTip("Home")
        self.home_btn.clicked.connect(self.navigate_home)

        self.history_btn = QPushButton()
        self.history_btn.setFixedSize(36, 36)
        self.history_btn.setToolTip("History")
        self.history_btn.clicked.connect(self.toggle_history_panel)

        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Enter URL or search")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        # Track real user edits (textEdited fires only for keyboard input,
        # never for programmatic setText) so redirects/loads can't clobber
        # what the user is typing.
        self.url_bar.textEdited.connect(self._on_url_text_edited)
        self.url_bar.installEventFilter(self)

        self.favorite_toggle_btn = QPushButton()
        self.favorite_toggle_btn.setFixedSize(36, 36)
        self.favorite_toggle_btn.clicked.connect(self.toggle_current_favorite)
        self.favorite_toggle_btn.setToolTip("Add current page to favorites")

        self.bookmark_btn = QPushButton()
        self.bookmark_btn.setFixedSize(36, 36)
        self.bookmark_btn.setToolTip("Favorites")
        self.bookmark_btn.clicked.connect(self.toggle_bookmarks)

        self.save_page_btn = QPushButton()
        self.save_page_btn.setFixedSize(36, 36)
        self.save_page_btn.setToolTip("Save Page")
        self.save_page_btn.clicked.connect(self.save_current_page)

        # Downloads toggle button
        self.downloads_toggle = QPushButton()
        self.downloads_toggle.setFixedSize(36, 36)
        self.downloads_toggle.setToolTip("Toggle Downloads")
        self.downloads_toggle.clicked.connect(self.toggle_downloads)

        left_group = QFrame()
        self.left_group = left_group
        left_group_layout = QHBoxLayout(left_group)
        left_group_layout.setContentsMargins(6, 6, 6, 6)
        left_group_layout.setSpacing(6)
        for button in [self.back_btn, self.forward_btn, self.reload_btn, self.home_btn, self.history_btn]:
            left_group_layout.addWidget(button)

        address_group = QFrame()
        self.address_group = address_group
        address_layout = QHBoxLayout(address_group)
        address_layout.setContentsMargins(10, 4, 10, 4)
        address_layout.setSpacing(8)
        self.address_icon = QLabel()
        self.address_icon.setStyleSheet("background: transparent; border: none;")
        address_layout.addWidget(self.address_icon)
        address_layout.addWidget(self.url_bar, 1)

        right_group = QFrame()
        self.right_group = right_group
        right_group_layout = QHBoxLayout(right_group)
        right_group_layout.setContentsMargins(6, 6, 6, 6)
        right_group_layout.setSpacing(6)
        for button in [self.favorite_toggle_btn, self.bookmark_btn, self.save_page_btn, self.downloads_toggle]:
            right_group_layout.addWidget(button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setTextVisible(False)
        # Anti-jump (2026-06-06): the 3px loading bar's slot is RESERVED at
        # all times — hiding it must not relayout the page below (the content
        # area jumped down on loadStarted and back up on loadFinished).
        # retainSizeWhenHidden keeps the layout geometry constant; show/hide
        # then only toggles painting.
        _pb_policy = self.progress_bar.sizePolicy()
        _pb_policy.setRetainSizeWhenHidden(True)
        self.progress_bar.setSizePolicy(_pb_policy)
        self.progress_bar.hide()

        self.screenshot_btn = QPushButton()
        self.screenshot_btn.setFixedSize(36, 36)
        self.screenshot_btn.setToolTip("Screenshot")
        self.screenshot_btn.clicked.connect(self.capture_screenshot)
        right_group_layout.insertWidget(right_group_layout.count() - 1, self.screenshot_btn)
        nav_layout.addWidget(left_group, 0)
        nav_layout.addWidget(address_group, 1)
        nav_layout.addWidget(right_group, 0)

        # Web view + saved items sidebar. The home URL is set ONCE in
        # setup_profile() after the persistent profile/page exist — setting it
        # here too kicked off a throwaway page load on the default profile.
        self.web_view = QWebEngineView()
        self.web_view.urlChanged.connect(self.on_url_changed)
        self.web_view.titleChanged.connect(self.on_title_changed)
        self.web_view.loadStarted.connect(self.on_load_started)
        self.web_view.loadProgress.connect(self.on_load_progress)
        self.web_view.loadFinished.connect(self.on_load_finished)

        self.content_row = QWidget()
        content_layout = QHBoxLayout(self.content_row)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(14)

        self.saved_items_sidebar = SavedItemsSidebar(self)
        self.saved_items_sidebar.item_activated.connect(self.open_saved_item)
        self.saved_items_sidebar.reveal_requested.connect(self.reveal_saved_item)
        self.saved_items_sidebar.screenshot_requested.connect(self.quick_capture_screenshot)
        content_layout.addWidget(self.saved_items_sidebar, 0)

        self.page_frame = QFrame()
        self.page_frame.setFrameShape(QFrame.StyledPanel)
        apply_shadow(self.page_frame, blur=28, y_offset=10, alpha=50)
        page_layout = QVBoxLayout(self.page_frame)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(0)
        page_layout.addWidget(self.web_view)
        content_layout.addWidget(self.page_frame, 1)

        browser_layout.setContentsMargins(12, 12, 12, 12)
        browser_layout.setSpacing(10)
        browser_layout.addWidget(nav_bar)
        browser_layout.addWidget(self.progress_bar)
        browser_layout.addWidget(self.content_row)
        
        # Download manager panel
        self.download_panel = DownloadManagerPanel(self.state_store)
        
        # Add to splitter
        self.splitter.addWidget(browser_container)
        self.splitter.addWidget(self.download_panel)
        self.splitter.setSizes([600, 200])
        
        # Hide download panel initially
        self.download_panel.hide()
        
        layout.addWidget(self.splitter)
        
        # Bookmark panel as floating dropdown
        self.bookmark_panel = BookmarkPanel(self.state_store, self)
        self.bookmark_panel.bookmark_clicked.connect(self.navigate_to_bookmark)
        self.bookmark_panel.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.bookmark_panel.setFixedSize(400, 500)
        self.bookmark_panel.hide()

        self.history_panel = HistoryPanel(self)
        self.history_panel.history_clicked.connect(self.navigate_to_bookmark)
        self.history_panel.clear_requested.connect(self.clear_page_history)
        self.history_panel.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.history_panel.setFixedSize(430, 500)
        self.history_panel.set_entries(self.page_history)
        self.history_panel.hide()

        self.restore_download_history()
        self.refresh_saved_items_sidebar()
        self.update_navigation_buttons()
        self.update_favorite_button()
        
    def setup_profile(self):
        self.profile = QWebEngineProfile("aipacs-web-browser", self)
        self.profile.setPersistentStoragePath(str(self.state_store.profile_dir / "storage"))
        self.profile.setCachePath(str(self.state_store.profile_dir / "cache"))
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.profile.setPersistentPermissionsPolicy(
            QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk
        )
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.page = QWebEnginePage(self.profile, self.web_view)
        self.web_view.setPage(self.page)
        self.profile.downloadRequested.connect(self.on_download_requested)
        self.page.featurePermissionRequested.connect(self.on_feature_permission_requested)
        self.web_view.setUrl(QUrl(HOME_URL))
        
    def navigate_to_url(self):
        url = self.url_bar.text().strip()
        if not url:
            return
        if not url.startswith(('http://', 'https://')):
            # Check if it's a valid domain or search query
            if '.' in url and ' ' not in url:
                url = 'https://' + url
            else:
                url = 'https://www.google.com/search?q=' + quote_plus(url)
        # The user committed this entry — programmatic updates may resume.
        self._url_user_editing = False
        self.web_view.setUrl(QUrl(url))

    def navigate_back(self):
        self.web_view.back()

    def navigate_forward(self):
        self.web_view.forward()

    def reload_page(self):
        """Reload — or Stop while a load is in flight (one button, two roles)."""
        if self._is_loading:
            self.web_view.stop()
        else:
            self.web_view.reload()

    def navigate_home(self):
        self.web_view.setUrl(QUrl(HOME_URL))

    def _on_url_text_edited(self, _text):
        self._url_user_editing = True

    def eventFilter(self, obj, event):
        if obj is getattr(self, "url_bar", None):
            if event.type() == QEvent.FocusIn:
                self._style_address_group(focused=True)
            elif event.type() == QEvent.FocusOut:
                # Abandoned edit (no Enter): restore the page's real URL so
                # the address bar always shows where the user actually is.
                if self._url_user_editing:
                    self._url_user_editing = False
                    self._sync_url_bar()
                self._style_address_group(focused=False)
        return super().eventFilter(obj, event)

    def _sync_url_bar(self, url_text=None):
        """Reflect the web view's URL in the address bar.

        - Never overwrites an in-progress user edit.
        - Skips no-op setText calls (no cursor/selection churn = no flicker).
        - Shows an empty field instead of the confusing ``about:blank``.
        """
        if self._url_user_editing:
            return
        text = url_text if url_text is not None else self.web_view.url().toString()
        if text == "about:blank":
            text = ""
        if self.url_bar.text() != text:
            self.url_bar.setText(text)
            if not self.url_bar.hasFocus():
                self.url_bar.setCursorPosition(0)

    def on_url_changed(self, url):
        self._sync_url_bar(url.toString())
        self.update_navigation_buttons()
        self.update_favorite_button()

    def on_title_changed(self, title):
        self.current_title = title.strip()

    def on_load_started(self):
        # Slot is permanently reserved (retainSizeWhenHidden) — show/hide
        # only toggles painting, never the layout (no content jump).
        self._is_loading = True
        self._update_reload_button_icon()
        self.progress_bar.setValue(0)
        self.progress_bar.show()

    def on_load_progress(self, value):
        self.progress_bar.setValue(value)

    def on_load_finished(self, ok):
        self._is_loading = False
        self._update_reload_button_icon()
        self.progress_bar.hide()
        # Failed/aborted loads still change canGoBack/canGoForward.
        self.update_navigation_buttons()
        if not ok:
            return
        url = self.web_view.url().toString()
        if not url or url == "about:blank":
            return
        # Show the final resolved URL once the page has settled.
        self._sync_url_bar(url)
        self.record_history(url, self.current_title or url)
        self.update_favorite_button()
        
    def toggle_bookmarks(self):
        if self.bookmark_panel.isVisible():
            self.bookmark_panel.hide()
        else:
            self.history_panel.hide()
            self.position_popup(self.bookmark_panel, self.bookmark_btn)
            self.bookmark_panel.show()

    def toggle_history_panel(self):
        if self.history_panel.isVisible():
            self.history_panel.hide()
        else:
            self.bookmark_panel.hide()
            self.position_popup(self.history_panel, self.history_btn)
            self.history_panel.show()
    
    def toggle_downloads(self):
        if self.download_panel.isVisible():
            self.download_panel.hide()
        else:
            self.download_panel.show()

    def toggle_current_favorite(self):
        url = self.web_view.url().toString()
        if not url or url == "about:blank":
            return
        existing_id = None
        for bookmark_id, bookmark in self.bookmark_panel.bookmarks.items():
            if bookmark.get("url") == url:
                existing_id = bookmark_id
                break
        if existing_id:
            del self.bookmark_panel.bookmarks[existing_id]
        else:
            self.bookmark_panel.bookmarks[str(datetime.now().timestamp())] = {
                "name": self.current_title or url,
                "url": url,
                "username": "",
                "password": "",
                "timestamp": datetime.now().isoformat(),
            }
        self.bookmark_panel.save_bookmarks()
        self.bookmark_panel.reload_bookmarks()
        self.update_favorite_button()
    
    def navigate_to_bookmark(self, url):
        """Navigate to a bookmarked URL"""
        if url:
            self._url_user_editing = False
            self.web_view.setUrl(QUrl(url))
            self._sync_url_bar(url)
            # Close the bookmark panel after navigation
            self.bookmark_panel.hide()
            self.history_panel.hide()

    def save_current_page(self):
        url = self.web_view.url().toString()
        if not url or url == "about:blank":
            return
        page_name = self.current_title or "page"
        safe_name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in page_name).strip()
        safe_name = (safe_name or "page").replace(" ", "_")[:80]
        save_path = str(self.make_unique_path(BROWSER_SAVED_PAGES_DIR / f"{safe_name}.html"))

        def _write_html(html):
            try:
                with open(save_path, "w", encoding="utf-8") as handle:
                    handle.write(html)
                page_entry = {
                    "title": self.current_title or url,
                    "url": url,
                    "save_path": save_path,
                    "saved_at": datetime.now().isoformat(),
                }
                self.saved_pages.insert(0, page_entry)
                self.saved_pages = self.saved_pages[: self.state_store.MAX_SAVED_PAGES]
                self.state_store.save_saved_pages(self.saved_pages)
                self.record_saved_item(
                    item_type="page",
                    title=page_entry["title"],
                    path=save_path,
                    url=url,
                    created_at=page_entry["saved_at"],
                )
                QMessageBox.information(self, "Page Saved", f"Saved to:\n{save_path}")
            except Exception as exc:
                QMessageBox.warning(self, "Save Failed", f"Could not save page:\n{exc}")

        self.web_view.page().toHtml(_write_html)

    def capture_screenshot(self):
        page_name = self.current_title or "web_capture"
        safe_name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in page_name).strip()
        safe_name = (safe_name or "web_capture").replace(" ", "_")[:80]
        dialog = ScreenshotDialog(self, default_name=safe_name)
        if dialog.exec() != QDialog.Accepted:
            return

        payload = dialog.payload()
        save_path = self.make_unique_path(
            BROWSER_SCREENSHOTS_DIR / f"{payload['name'].replace(' ', '_')}.png"
        )
        if payload["mode"] == "browser":
            pixmap = self.content_row.grab()
        else:
            pixmap = self.page_frame.grab()
        if pixmap.isNull():
            QMessageBox.warning(self, "Capture Failed", "The browser view could not be captured.")
            return
        if not pixmap.save(str(save_path), "PNG"):
            QMessageBox.warning(self, "Capture Failed", "The screenshot could not be written to disk.")
            return

        created_at = datetime.now().isoformat()
        self.record_saved_item(
            item_type="screenshot",
            title=Path(save_path).stem,
            path=str(save_path),
            url=self.web_view.url().toString(),
            created_at=created_at,
        )
        QMessageBox.information(self, "Screenshot Saved", f"Saved to:\n{save_path}")

    def quick_capture_screenshot(self):
        page_name = self.current_title or "screenshot"
        safe_name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in page_name).strip()
        safe_name = (safe_name or "screenshot").replace(" ", "_")[:60]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = self.make_unique_path(
            BROWSER_SCREENSHOTS_DIR / f"{safe_name}_{timestamp}.png"
        )
        pixmap = self.page_frame.grab()
        if pixmap.isNull():
            QMessageBox.warning(self, "Capture Failed", "The screenshot could not be captured.")
            return
        if not pixmap.save(str(save_path), "PNG"):
            QMessageBox.warning(self, "Capture Failed", "The screenshot could not be written to disk.")
            return

        created_at = datetime.now().isoformat()
        self.record_saved_item(
            item_type="screenshot",
            title=Path(save_path).stem,
            path=str(save_path),
            url=self.web_view.url().toString(),
            created_at=created_at,
        )
            
    def on_download_requested(self, download):
        filename = download.suggestedFileName() or "download"

        save_path = str(self.make_unique_path(Path(self.downloads_path) / filename))

        download.setDownloadDirectory(str(Path(save_path).parent))
        download.setDownloadFileName(Path(save_path).name)
        download_id = str(id(download))

        self.download_panel.show()

        download_item = self.download_panel.add_download(
            download_id,
            os.path.basename(save_path),
            download.url().toString(),
            save_path,
            download_request=download,
        )

        download.downloadProgress.connect(
            lambda received, total: download_item.update_progress(received, total)
        )

        download.isFinishedChanged.connect(
            lambda: self.on_download_finished(download, download_item)
        )

        download.accept()
            
            
    def on_download_finished(self, download, download_item):
        if download.isFinished() and download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            download_item.set_completed()
            created_at = datetime.now().isoformat()
            self.download_panel.download_history.insert(0, {
                'filename': Path(download_item.save_path).name,
                'url': download.url().toString(),
                'save_path': download_item.save_path,
                'timestamp': created_at
            })
            self.download_panel.download_history = self.download_panel.download_history[: self.state_store.MAX_DOWNLOAD_HISTORY]
            self.download_panel.save_history()
            self.record_saved_item(
                item_type="download",
                title=Path(download_item.save_path).name,
                path=download_item.save_path,
                url=download.url().toString(),
                created_at=created_at,
            )
        else:
            download_item.set_error("Download failed")
    
    def on_feature_permission_requested(self, securityOrigin, feature):
        self.web_view.page().setFeaturePermission(
            securityOrigin,
            feature,
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser,
        )

    def record_history(self, url, title):
        self.page_history = [entry for entry in self.page_history if entry.get("url") != url]
        self.page_history.insert(0, {
            "title": title,
            "url": url,
            "visited_at": datetime.now().isoformat(),
        })
        self.page_history = self.page_history[: self.state_store.MAX_PAGE_HISTORY]
        self.state_store.save_page_history(self.page_history)
        self.history_panel.set_entries(self.page_history)

    def clear_page_history(self):
        self.page_history = []
        self.state_store.save_page_history(self.page_history)
        self.history_panel.set_entries(self.page_history)

    def restore_download_history(self):
        for entry in reversed(self.download_panel.download_history[:10]):
            history_id = f"history-{entry.get('timestamp')}-{entry.get('filename')}"
            if history_id in self.download_panel.downloads:
                continue
            item = self.download_panel.add_download(
                history_id,
                entry.get("filename", "download"),
                entry.get("url", ""),
                entry.get("save_path", ""),
            )
            item.set_completed()
            item.status_label.setText(
                f"Saved {entry.get('timestamp', '')[:16].replace('T', ' ')}"
            )

    def refresh_saved_items_sidebar(self):
        self.saved_items_sidebar.set_items(self.saved_items)

    def record_saved_item(self, item_type, title, path, url="", created_at=None):
        created_at = created_at or datetime.now().isoformat()
        self.saved_items = [
            item for item in self.saved_items
            if item.get("path") != path
        ]
        self.saved_items.insert(0, {
            "item_type": item_type,
            "title": title,
            "path": path,
            "url": url,
            "created_at": created_at,
        })
        self.saved_items = self.saved_items[: self.state_store.MAX_SAVED_ITEMS]
        self.state_store.save_saved_items(self.saved_items)
        self.refresh_saved_items_sidebar()

    def open_saved_item(self, entry):
        path = entry.get("path", "")
        url = entry.get("url", "")
        if path and Path(path).exists():
            suffix = Path(path).suffix.lower()
            if suffix in {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".mp4", ".webm", ".pdf", ".txt"}:
                self.web_view.setUrl(QUrl.fromLocalFile(path))
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        if url:
            self.web_view.setUrl(QUrl(url))

    def reveal_saved_item(self, entry):
        path = entry.get("path", "")
        if not path:
            return
        target = Path(path)
        folder = target.parent if target.exists() else Path(self.downloads_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def make_unique_path(self, target_path):
        target_path = Path(target_path)
        counter = 1
        candidate = target_path
        while candidate.exists():
            candidate = target_path.with_name(
                f"{target_path.stem}_{counter}{target_path.suffix}"
            )
            counter += 1
        return candidate

    def update_navigation_buttons(self):
        history = self.web_view.history()
        self.back_btn.setEnabled(history.canGoBack())
        self.forward_btn.setEnabled(history.canGoForward())

    def update_favorite_button(self):
        if not hasattr(self, "bookmark_panel"):
            return  # called from _apply_theme_styles before panels exist
        url = self.web_view.url().toString()
        is_favorite = any(
            bookmark.get("url") == url for bookmark in self.bookmark_panel.bookmarks.values()
        )
        t = self._theme
        icon_name = 'fa5s.star' if is_favorite else 'fa5.star'
        color = t['warning'] if is_favorite else t['text_primary']
        self.favorite_toggle_btn.setIcon(qta.icon(icon_name, color=color))
        self.favorite_toggle_btn.setToolTip(
            "Remove current page from favorites" if is_favorite else "Add current page to favorites"
        )

    def position_popup(self, panel, anchor_button):
        button_pos = anchor_button.mapToGlobal(anchor_button.rect().bottomLeft())
        screen = QApplication.screenAt(button_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            panel.move(button_pos.x(), button_pos.y() + 6)
            return

        geometry = screen.availableGeometry()
        x = button_pos.x() - panel.width() + anchor_button.width()
        y = button_pos.y() + 6

        if x < geometry.left() + 8:
            x = max(geometry.left() + 8, anchor_button.mapToGlobal(anchor_button.rect().topLeft()).x())
        if x + panel.width() > geometry.right() - 8:
            x = max(geometry.left() + 8, geometry.right() - panel.width() - 8)
        if y + panel.height() > geometry.bottom() - 8:
            y = max(geometry.top() + 8, anchor_button.mapToGlobal(anchor_button.rect().topLeft()).y() - panel.height() - 8)

        panel.move(x, y)


