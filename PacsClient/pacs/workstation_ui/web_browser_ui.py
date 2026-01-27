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
import json
import qtawesome as qta
import base64


class BookmarkDialog(QDialog):
    """Dialog for adding/editing a bookmark"""
    
    def __init__(self, parent=None, bookmark_data=None):
        super().__init__(parent)
        self.bookmark_data = bookmark_data
        self.setWindowTitle("Add Bookmark" if not bookmark_data else "Edit Bookmark")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setStyleSheet("""
            QDialog {
                background-color: #2d2d2d;
            }
        """)
        self.setup_ui()
        
        if bookmark_data:
            self.load_bookmark_data()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Bookmark Details")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
        
        # Form layout
        form_layout = QFormLayout()
        form_layout.setSpacing(15)
        form_layout.setLabelAlignment(Qt.AlignLeft)
        
        # Style for labels
        label_style = "color: #ffffff; font-size: 13px; font-weight: bold;"
        
        # Name field
        name_label = QLabel("Name:")
        name_label.setStyleSheet(label_style)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g., STATdx")
        self.name_edit.setMinimumHeight(40)
        self.name_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #555;
                border-radius: 6px;
                font-size: 14px;
                color: #ffffff;
                background-color: #3d3d3d;
            }
            QLineEdit:focus {
                border: 2px solid #4285f4;
                background-color: #4d4d4d;
            }
        """)
        
        # URL field
        url_label = QLabel("URL:")
        url_label.setStyleSheet(label_style)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com")
        self.url_edit.setMinimumHeight(40)
        self.url_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #555;
                border-radius: 6px;
                font-size: 14px;
                color: #ffffff;
                background-color: #3d3d3d;
            }
            QLineEdit:focus {
                border: 2px solid #4285f4;
                background-color: #4d4d4d;
            }
        """)
        
        # Username field
        username_label = QLabel("Username:")
        username_label.setStyleSheet(label_style)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("Username (optional)")
        self.username_edit.setMinimumHeight(40)
        self.username_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #555;
                border-radius: 6px;
                font-size: 14px;
                color: #ffffff;
                background-color: #3d3d3d;
            }
            QLineEdit:focus {
                border: 2px solid #4285f4;
                background-color: #4d4d4d;
            }
        """)
        
        # Password field
        password_label = QLabel("Password:")
        password_label.setStyleSheet(label_style)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Password (optional)")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumHeight(40)
        self.password_edit.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #555;
                border-radius: 6px;
                font-size: 14px;
                color: #ffffff;
                background-color: #3d3d3d;
            }
            QLineEdit:focus {
                border: 2px solid #4285f4;
                background-color: #4d4d4d;
            }
        """)
        
        # Show password checkbox
        self.show_password_cb = QCheckBox("Show Password")
        self.show_password_cb.stateChanged.connect(self.toggle_password_visibility)
        self.show_password_cb.setStyleSheet("color: #cccccc; font-size: 13px;")
        
        form_layout.addRow(name_label, self.name_edit)
        form_layout.addRow(url_label, self.url_edit)
        form_layout.addRow(username_label, self.username_edit)
        form_layout.addRow(password_label, self.password_edit)
        form_layout.addRow("", self.show_password_cb)
        
        layout.addLayout(form_layout)
        
        # Note
        note = QLabel("Note: Credentials are stored locally and encoded.")
        note.setStyleSheet("color: #aaaaaa; font-size: 12px; font-style: italic;")
        layout.addWidget(note)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setMinimumHeight(45)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 28px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        save_btn = QPushButton("Save")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(45)
        save_btn.clicked.connect(self.accept)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4285f4;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px 28px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #357ae8;
            }
        """)
        
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
        name_label.setStyleSheet("font-size: 13px; color: #ffffff; padding: 4px;")
        name_label.setWordWrap(False)
        
        # Minimal icon buttons
        button_style = """
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 12px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """
        
        # Visit button
        visit_btn = QPushButton()
        visit_btn.setIcon(qta.icon('fa5s.external-link-alt', color='#aaaaaa'))
        visit_btn.setFixedSize(24, 24)
        visit_btn.setToolTip("Visit")
        visit_btn.clicked.connect(lambda: self.clicked.emit(self.bookmark_data.get('url', '')))
        visit_btn.setStyleSheet(button_style)
        
        # Auto-login button (if credentials exist)
        login_btn = None
        if has_credentials:
            login_btn = QPushButton()
            login_btn.setIcon(qta.icon('fa5s.sign-in-alt', color='#81C784'))
            login_btn.setFixedSize(24, 24)
            login_btn.setToolTip("Auto-fill")
            login_btn.clicked.connect(self.auto_login)
            login_btn.setStyleSheet(button_style)
        
        # Edit button
        edit_btn = QPushButton()
        edit_btn.setIcon(qta.icon('fa5s.edit', color='#aaaaaa'))
        edit_btn.setFixedSize(24, 24)
        edit_btn.setToolTip("Edit")
        edit_btn.clicked.connect(self.edit_bookmark)
        edit_btn.setStyleSheet(button_style)
        
        # Delete button
        delete_btn = QPushButton()
        delete_btn.setIcon(qta.icon('fa5s.trash', color='#aaaaaa'))
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
        self.setStyleSheet("""
            QFrame {
                background-color: transparent;
                border: none;
                border-radius: 4px;
            }
            QFrame:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
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
        
        # Create custom dialog with dark theme
        msg = QMessageBox(self)
        msg.setWindowTitle("Login Credentials")
        msg.setIcon(QMessageBox.Information)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #2d2d2d;
            }
            QMessageBox QLabel {
                color: #ffffff;
                font-size: 14px;
                min-width: 350px;
            }
            QMessageBox QPushButton {
                background-color: #4285f4;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-weight: bold;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background-color: #357ae8;
            }
        """)
        
        msg_text = f"""
        <div style='color: #ffffff;'>
        <p style='font-size: 15px; margin-bottom: 15px;'><b>Website:</b> <span style='color: #4285f4;'>{self.bookmark_data.get('name', 'Unknown')}</span></p>
        <p style='font-size: 14px; margin-bottom: 10px;'><b>Username:</b> <span style='color: #81C784;'>{username}</span></p>
        <p style='font-size: 14px; margin-bottom: 15px;'><b>Password:</b> <span style='color: #81C784;'>{password}</span></p>
        <p style='font-size: 12px; color: #aaaaaa; font-style: italic;'>Please enter these credentials on the website.</p>
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
    """Bookmark Manager Panel"""
    
    bookmark_clicked = Signal(str)  # Emits URL to navigate
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bookmarks = {}
        self.bookmarks_file = "browser_bookmarks.json"
        self.setup_ui()
        self.load_bookmarks()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Set overall panel style with shadow effect
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                border: 2px solid #555;
                border-radius: 8px;
            }
        """)
        
        # Add shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)
        
        # Header
        header = QWidget()
        header.setFixedHeight(42)
        header.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333; border-top-left-radius: 8px; border-top-right-radius: 8px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        
        title = QLabel("Bookmarks")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        
        self.add_btn = QPushButton()
        self.add_btn.setIcon(qta.icon('fa5s.plus', color='#aaaaaa'))
        self.add_btn.setFixedSize(28, 28)
        self.add_btn.setToolTip("Add Bookmark")
        self.add_btn.clicked.connect(self.add_bookmark)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 14px;
                padding: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.15);
            }
        """)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.add_btn)
        
        # Bookmarks area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background-color: #1e1e1e; 
                border-bottom-left-radius: 8px; 
                border-bottom-right-radius: 8px;
            }
        """)
        
        self.bookmarks_widget = QWidget()
        self.bookmarks_widget.setStyleSheet("background-color: #1e1e1e;")
        self.bookmarks_layout = QVBoxLayout(self.bookmarks_widget)
        self.bookmarks_layout.setAlignment(Qt.AlignTop)
        self.bookmarks_layout.setSpacing(2)
        self.bookmarks_layout.setContentsMargins(8, 8, 8, 8)
        
        self.scroll_area.setWidget(self.bookmarks_widget)
        
        # Empty state
        self.empty_label = QLabel("No bookmarks yet")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #888888; font-size: 13px; padding: 40px;")
        
        layout.addWidget(header)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.empty_label)
        
        self.update_empty_state()
    
    def add_bookmark(self, current_url=None):
        dialog = BookmarkDialog(self)
        if current_url:
            dialog.url_edit.setText(current_url)
        
        if dialog.exec() == QDialog.Accepted:
            bookmark_data = dialog.get_bookmark_data()
            bookmark_id = str(datetime.now().timestamp())
            self.bookmarks[bookmark_id] = bookmark_data
            self.create_bookmark_widget(bookmark_id, bookmark_data)
            self.save_bookmarks()
            self.update_empty_state()
    
    def create_bookmark_widget(self, bookmark_id, bookmark_data):
        bookmark_item = BookmarkItemWidget(bookmark_id, bookmark_data)
        bookmark_item.clicked.connect(self.bookmark_clicked.emit)
        bookmark_item.edited.connect(self.edit_bookmark)
        bookmark_item.deleted.connect(self.delete_bookmark)
        self.bookmarks_layout.addWidget(bookmark_item)
        return bookmark_item
    
    def edit_bookmark(self, data):
        bookmark_id = data['id']
        bookmark_data = data['data']
        if bookmark_id in self.bookmarks:
            self.bookmarks[bookmark_id] = bookmark_data
            self.save_bookmarks()
            self.reload_bookmarks()
    
    def delete_bookmark(self, bookmark_id):
        reply = QMessageBox.question(
            self,
            "Delete Bookmark",
            "Are you sure you want to delete this bookmark?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if bookmark_id in self.bookmarks:
                del self.bookmarks[bookmark_id]
                self.save_bookmarks()
                self.reload_bookmarks()
    
    def reload_bookmarks(self):
        # Clear existing widgets
        for i in reversed(range(self.bookmarks_layout.count())):
            widget = self.bookmarks_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # Recreate widgets
        for bookmark_id, bookmark_data in self.bookmarks.items():
            self.create_bookmark_widget(bookmark_id, bookmark_data)
        
        self.update_empty_state()
    
    def update_empty_state(self):
        has_bookmarks = len(self.bookmarks) > 0
        self.scroll_area.setVisible(has_bookmarks)
        self.empty_label.setVisible(not has_bookmarks)
    
    def save_bookmarks(self):
        try:
            with open(self.bookmarks_file, 'w') as f:
                json.dump(self.bookmarks, f, indent=2)
        except Exception as e:
            print(f"Error saving bookmarks: {e}")
    
    def load_bookmarks(self):
        try:
            if os.path.exists(self.bookmarks_file):
                with open(self.bookmarks_file, 'r') as f:
                    self.bookmarks = json.load(f)
                    for bookmark_id, bookmark_data in self.bookmarks.items():
                        self.create_bookmark_widget(bookmark_id, bookmark_data)
                self.update_empty_state()
        except Exception as e:
            print(f"Error loading bookmarks: {e}")
            self.bookmarks = {}


class DownloadItemWidget(QFrame):
    """Widget for displaying a single download"""
    
    canceled = Signal(str)
    paused = Signal(str)
    resumed = Signal(str)
    
    def __init__(self, download_id, filename, url, save_path, parent=None):
        super().__init__(parent)
        self.download_id = download_id
        self.filename = filename
        self.url = url
        self.save_path = save_path
        self.start_time = datetime.now()
        self.is_paused = False
        self.is_completed = False
        self.is_canceled = False
        
        self.setup_ui()
        
    def setup_ui(self):
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Top row: Icon, filename, controls
        top_layout = QHBoxLayout()
        
        # Icon
        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.file', color='#4285f4').pixmap(28, 28))
        icon_label.setFixedSize(32, 32)
        
        # Filename
        self.name_label = QLabel(self.filename)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 12px; color: #333;")
        self.name_label.setWordWrap(False)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Control buttons
        self.pause_btn = QPushButton()
        self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
        self.pause_btn.setFixedSize(32, 32)
        self.pause_btn.setToolTip("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        
        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(qta.icon('fa5s.times', color='white'))
        self.cancel_btn.setFixedSize(32, 32)
        self.cancel_btn.setToolTip("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        
        self.open_btn = QPushButton()
        self.open_btn.setIcon(qta.icon('fa5s.folder-open', color='white'))
        self.open_btn.setFixedSize(32, 32)
        self.open_btn.setToolTip("Open File")
        self.open_btn.clicked.connect(self.open_file)
        self.open_btn.hide()
        self.open_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
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
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
                background-color: #f5f5f5;
            }
            QProgressBar::chunk {
                background-color: #4285f4;
                border-radius: 3px;
            }
        """)
        
        # Status labels
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Starting download...")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        
        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: #666; font-size: 11px;")
        self.speed_label.setAlignment(Qt.AlignRight)
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.speed_label)
        
        # Add to main layout
        layout.addLayout(top_layout)
        layout.addWidget(self.progress_bar)
        layout.addLayout(status_layout)
        
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 8px;
            }
        """)
        
    def toggle_pause(self):
        if not self.is_paused:
            self.is_paused = True
            self.pause_btn.setIcon(qta.icon('fa5s.play', color='white'))
            self.pause_btn.setToolTip("Resume")
            self.status_label.setText("Paused")
            self.paused.emit(self.download_id)
        else:
            self.is_paused = False
            self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
            self.pause_btn.setToolTip("Pause")
            self.status_label.setText("Downloading...")
            self.resumed.emit(self.download_id)
            
    def cancel_download(self):
        self.is_canceled = True
        self.status_label.setText("Canceled")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #f44336;
                border-radius: 3px;
            }
        """)
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
        self.progress_bar.setValue(100)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        self.status_label.setText("Download completed")
        self.speed_label.setText("")
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.open_btn.show()
        
    def set_error(self, error_msg):
        self.status_label.setText(f"Error: {error_msg}")
        self.progress_bar.setStyleSheet("""
            QProgressBar::chunk {
                background-color: #f44336;
            }
        """)
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.downloads = {}
        self.download_history = []
        self.history_file = "browser_download_history.json"
        self.setup_ui()
        self.load_history()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #f8f9fa; border-bottom: 1px solid #dee2e6;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        title = QLabel("Downloads")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(qta.icon('fa5s.trash', color='white'))
        self.clear_btn.setText("Clear Completed")
        self.clear_btn.clicked.connect(self.clear_completed)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.clear_btn)
        
        # Downloads area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #f5f5f5; }")
        
        self.downloads_widget = QWidget()
        self.downloads_layout = QVBoxLayout(self.downloads_widget)
        self.downloads_layout.setAlignment(Qt.AlignTop)
        self.downloads_layout.setSpacing(10)
        self.downloads_layout.setContentsMargins(15, 15, 15, 15)
        
        self.scroll_area.setWidget(self.downloads_widget)
        
        # Empty state
        self.empty_label = QLabel("No downloads yet")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #999; font-size: 14px; padding: 50px;")
        
        layout.addWidget(header)
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.empty_label)
        
        self.update_empty_state()
        
    def add_download(self, download_id, filename, url, save_path):
        download_item = DownloadItemWidget(download_id, filename, url, save_path)
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
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.download_history, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")
            
    def load_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.download_history = json.load(f)
        except Exception as e:
            print(f"Error loading history: {e}")
            self.download_history = []


class WebBrowserWidget(QWidget):
    """Main Web Browser Widget for AIPacs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.downloads_path = str(Path.home() / "Downloads")
        os.makedirs(self.downloads_path, exist_ok=True)
        
        self.setup_ui()
        self.setup_profile()
        
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
        
        # Navigation bar
        nav_bar = QWidget()
        nav_bar.setFixedHeight(50)
        nav_bar.setStyleSheet("background-color: #ffffff; border-bottom: 1px solid #ddd;")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(10, 5, 10, 5)
        nav_layout.setSpacing(8)
        
        # Navigation buttons
        self.back_btn = QPushButton()
        self.back_btn.setIcon(qta.icon('fa5s.arrow-left', color='#333'))
        self.back_btn.setFixedSize(36, 36)
        self.back_btn.setToolTip("Back")
        self.back_btn.clicked.connect(self.navigate_back)
        
        self.forward_btn = QPushButton()
        self.forward_btn.setIcon(qta.icon('fa5s.arrow-right', color='#333'))
        self.forward_btn.setFixedSize(36, 36)
        self.forward_btn.setToolTip("Forward")
        self.forward_btn.clicked.connect(self.navigate_forward)
        
        self.reload_btn = QPushButton()
        self.reload_btn.setIcon(qta.icon('fa5s.sync', color='#333'))
        self.reload_btn.setFixedSize(36, 36)
        self.reload_btn.setToolTip("Reload")
        self.reload_btn.clicked.connect(self.reload_page)
        
        self.home_btn = QPushButton()
        self.home_btn.setIcon(qta.icon('fa5s.home', color='#333'))
        self.home_btn.setFixedSize(36, 36)
        self.home_btn.setToolTip("Home")
        self.home_btn.clicked.connect(self.navigate_home)
        
        # URL bar
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Enter URL or search...")
        self.url_bar.returnPressed.connect(self.navigate_to_url)
        self.url_bar.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 20px;
                background-color: #f5f5f5;
                font-size: 13px;
                color: #000000;
            }
            QLineEdit:focus {
                border: 1px solid #4285f4;
                background-color: white;
                color: #000000;
            }
        """)
        
        # Bookmark button
        self.bookmark_btn = QPushButton()
        self.bookmark_btn.setIcon(qta.icon('fa5s.star', color='#333'))
        self.bookmark_btn.setFixedSize(36, 36)
        self.bookmark_btn.setToolTip("Bookmarks")
        self.bookmark_btn.clicked.connect(self.toggle_bookmarks)
        
        # Downloads toggle button
        self.downloads_toggle = QPushButton()
        self.downloads_toggle.setIcon(qta.icon('fa5s.download', color='#333'))
        self.downloads_toggle.setFixedSize(36, 36)
        self.downloads_toggle.setToolTip("Toggle Downloads")
        self.downloads_toggle.clicked.connect(self.toggle_downloads)
        
        # Style for nav buttons
        button_style = """
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
        """
        self.back_btn.setStyleSheet(button_style)
        self.forward_btn.setStyleSheet(button_style)
        self.reload_btn.setStyleSheet(button_style)
        self.home_btn.setStyleSheet(button_style)
        self.bookmark_btn.setStyleSheet(button_style)
        self.downloads_toggle.setStyleSheet(button_style)
        
        nav_layout.addWidget(self.back_btn)
        nav_layout.addWidget(self.forward_btn)
        nav_layout.addWidget(self.reload_btn)
        nav_layout.addWidget(self.home_btn)
        nav_layout.addWidget(self.url_bar, 1)
        nav_layout.addWidget(self.bookmark_btn)
        nav_layout.addWidget(self.downloads_toggle)
        
        # Web view
        self.web_view = QWebEngineView()
        self.web_view.setUrl(QUrl("https://www.google.com"))
        self.web_view.urlChanged.connect(self.on_url_changed)
        self.web_view.titleChanged.connect(self.on_title_changed)
        
        # Setup permission handler for microphone, camera, etc.
        self.web_view.page().featurePermissionRequested.connect(self.on_feature_permission_requested)
        
        browser_layout.addWidget(nav_bar)
        browser_layout.addWidget(self.web_view)
        
        # Download manager panel
        self.download_panel = DownloadManagerPanel()
        
        # Add to splitter
        self.splitter.addWidget(browser_container)
        self.splitter.addWidget(self.download_panel)
        self.splitter.setSizes([600, 200])
        
        # Hide download panel initially
        self.download_panel.hide()
        
        layout.addWidget(self.splitter)
        
        # Bookmark panel as floating dropdown
        self.bookmark_panel = BookmarkPanel(self)
        self.bookmark_panel.bookmark_clicked.connect(self.navigate_to_bookmark)
        self.bookmark_panel.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.bookmark_panel.setFixedSize(400, 500)
        self.bookmark_panel.hide()
        
    def setup_profile(self):
        profile = QWebEngineProfile.defaultProfile()
        profile.downloadRequested.connect(self.on_download_requested)
        
    def navigate_to_url(self):
        url = self.url_bar.text()
        if not url.startswith(('http://', 'https://')):
            # Check if it's a valid domain or search query
            if '.' in url and ' ' not in url:
                url = 'https://' + url
            else:
                # Search on Google
                url = 'https://www.google.com/search?q=' + url.replace(' ', '+')
        self.web_view.setUrl(QUrl(url))
        
    def navigate_back(self):
        self.web_view.back()
        
    def navigate_forward(self):
        self.web_view.forward()
        
    def reload_page(self):
        self.web_view.reload()
        
    def navigate_home(self):
        self.web_view.setUrl(QUrl("https://www.google.com"))
        
    def on_url_changed(self, url):
        self.url_bar.setText(url.toString())
        
    def on_title_changed(self, title):
        pass  # Can be used to update parent tab title
        
    def toggle_bookmarks(self):
        if self.bookmark_panel.isVisible():
            self.bookmark_panel.hide()
        else:
            # Position the panel below the bookmark button
            button_pos = self.bookmark_btn.mapToGlobal(self.bookmark_btn.rect().bottomLeft())
            panel_x = button_pos.x() - self.bookmark_panel.width() + self.bookmark_btn.width()
            panel_y = button_pos.y() + 5
            self.bookmark_panel.move(panel_x, panel_y)
            self.bookmark_panel.show()
    
    def toggle_downloads(self):
        if self.download_panel.isVisible():
            self.download_panel.hide()
        else:
            self.download_panel.show()
    
    def navigate_to_bookmark(self, url):
        """Navigate to a bookmarked URL"""
        if url:
            self.web_view.setUrl(QUrl(url))
            self.url_bar.setText(url)
            # Close the bookmark panel after navigation
            self.bookmark_panel.hide()
            
    def on_download_requested(self, download):
        filename = download.suggestedFileName()
        
        # Ask for save location
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save File",
            os.path.join(self.downloads_path, filename),
            "All Files (*.*)"
        )
        
        if save_path:
            download.setPath(save_path)
            download_id = str(id(download))
            
            # Show download panel
            self.download_panel.show()
            
            # Add to download manager
            download_item = self.download_panel.add_download(
                download_id,
                os.path.basename(save_path),
                download.url().toString(),
                save_path
            )
            
            # Connect signals
            download.downloadProgress.connect(
                lambda received, total: download_item.update_progress(received, total)
            )
            
            download.isFinishedChanged.connect(
                lambda: self.on_download_finished(download, download_item)
            )
            
            # Accept download
            download.accept()
            
            # Save to history
            self.download_panel.download_history.append({
                'filename': filename,
                'url': download.url().toString(),
                'save_path': save_path,
                'timestamp': datetime.now().isoformat()
            })
            self.download_panel.save_history()
            
    def on_download_finished(self, download, download_item):
        if download.isFinished() and download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            download_item.set_completed()
        else:
            download_item.set_error("Download failed")
    
    def on_feature_permission_requested(self, securityOrigin, feature):
        """
        Handle permission requests for microphone, camera, geolocation, etc.
        Automatically grant permissions for media devices (microphone and camera).
        """
        # Import the feature enum
        from PySide6.QtWebEngineCore import QWebEnginePage
        
        # Automatically grant permission for microphone and camera
        if feature in [
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture
        ]:
            print(f"Granting permission for {feature} from {securityOrigin.toString()}")
            self.web_view.page().setFeaturePermission(
                securityOrigin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            )
        else:
            # For other features, you might want to ask the user or deny
            # For now, we'll grant them as well
            print(f"Granting permission for {feature} from {securityOrigin.toString()}")
            self.web_view.page().setFeaturePermission(
                securityOrigin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            )


