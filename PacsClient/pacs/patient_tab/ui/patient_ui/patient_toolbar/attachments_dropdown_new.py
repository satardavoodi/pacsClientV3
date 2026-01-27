"""
Dropdown widget for displaying saved recordings and captured images with audio player
"""
import os
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QFrame, QMessageBox, QSlider
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPixmap, QDesktopServices, QCursor
from PySide6.QtCore import QUrl
import qtawesome as qta
from PacsClient.utils.config import ATTACHMENT_PATH
import sounddevice as sd
import soundfile as sf
import numpy as np


class AttachmentItemWidget(QWidget):
    """Single item widget for attachment (audio or image)"""
    
    def __init__(self, file_path, file_type, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_type = file_type  # 'audio' or 'image'
        self.is_playing = False
        
        # Audio playback state
        self.audio_data = None
        self.sample_rate = None
        self.playback_position = 0
        self.is_seeking = False
        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self._update_playback_position)
        
        self._setup_ui()
        
        # Load audio if it's an audio file
        if self.file_type == 'audio':
            self._load_audio()
    
    def _load_audio(self):
        """Load audio file for playback"""
        try:
            self.audio_data, self.sample_rate = sf.read(self.file_path)
        except Exception as e:
            print(f"Error loading audio: {e}")
            self.audio_data = None
    
    def _setup_ui(self):
        """Setup UI for attachment item"""
        if self.file_type == 'image':
            self.setFixedHeight(120)
        else:
            self.setFixedHeight(140)  # Increased height for audio player
            
        self.setStyleSheet("""
            QWidget {
                background: #374151;
                border-radius: 6px;
            }
            QWidget:hover {
                background: #4b5563;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        
        # Top section with thumbnail and info
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        # Thumbnail/Preview
        if self.file_type == 'image':
            # Show image thumbnail
            thumbnail_label = QLabel()
            thumbnail_label.setFixedSize(100, 100)
            thumbnail_label.setStyleSheet("""
                QLabel {
                    background: #1f2937;
                    border: 2px solid #4b5563;
                    border-radius: 6px;
                }
            """)
            thumbnail_label.setScaledContents(True)
            thumbnail_label.setAlignment(Qt.AlignCenter)
            
            try:
                pixmap = QPixmap(self.file_path)
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    thumbnail_label.setPixmap(scaled_pixmap)
                else:
                    # Fallback icon
                    icon = qta.icon('fa5s.image', color='#3b82f6', scale_factor=2.0)
                    thumbnail_label.setPixmap(icon.pixmap(QSize(50, 50)))
            except:
                icon = qta.icon('fa5s.image', color='#3b82f6', scale_factor=2.0)
                thumbnail_label.setPixmap(icon.pixmap(QSize(50, 50)))
            
            top_layout.addWidget(thumbnail_label)
        else:
            # Audio waveform placeholder
            audio_viz = QWidget()
            audio_viz.setFixedSize(60, 60)
            audio_viz.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #064e3b, stop:0.5 #059669, stop:1 #064e3b);
                    border: 2px solid #10b981;
                    border-radius: 6px;
                }
            """)
            
            viz_layout = QVBoxLayout(audio_viz)
            viz_layout.setAlignment(Qt.AlignCenter)
            icon_label = QLabel()
            icon = qta.icon('fa5s.microphone', color='#34d399', scale_factor=1.5)
            icon_label.setPixmap(icon.pixmap(QSize(30, 30)))
            icon_label.setAlignment(Qt.AlignCenter)
            viz_layout.addWidget(icon_label)
            
            top_layout.addWidget(audio_viz)
        
        # Date/time only (no filename)
        try:
            mod_time = os.path.getmtime(self.file_path)
            mod_date = datetime.fromtimestamp(mod_time).strftime("%Y-%m-%d\n%H:%M:%S")
        except:
            mod_date = "Unknown"
        
        date_label = QLabel(mod_date)
        date_label.setStyleSheet("""
            QLabel {
                color: #d1d5db;
                font-size: 11px;
                font-weight: 500;
                font-family: 'Roboto', sans-serif;
            }
        """)
        date_label.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(date_label)
        top_layout.addStretch()
        
        # Action buttons container
        actions_layout = QVBoxLayout()
        actions_layout.setSpacing(6)
        
        if self.file_type == 'audio':
            # Play button (will be updated to pause when playing)
            self.play_btn = QPushButton()
            self.play_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
            self.play_btn.setIconSize(QSize(16, 16))
            self.play_btn.setFixedSize(32, 32)
            self.play_btn.setToolTip('Play Audio')
            self.play_btn.setStyleSheet("""
                QPushButton {
                    background: #1f2937;
                    border: 1px solid #10b981;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background: #10b981;
                    border-color: #10b981;
                }
            """)
            self.play_btn.setCursor(Qt.PointingHandCursor)
            self.play_btn.clicked.connect(self._toggle_play)
            actions_layout.addWidget(self.play_btn)
            
            # Stop button
            stop_btn = QPushButton()
            stop_btn.setIcon(qta.icon('fa5s.stop', color='#ef4444'))
            stop_btn.setIconSize(QSize(16, 16))
            stop_btn.setFixedSize(32, 32)
            stop_btn.setToolTip('Stop Audio')
            stop_btn.setStyleSheet("""
                QPushButton {
                    background: #1f2937;
                    border: 1px solid #ef4444;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background: #ef4444;
                    border-color: #ef4444;
                }
            """)
            stop_btn.setCursor(Qt.PointingHandCursor)
            stop_btn.clicked.connect(self._stop_audio)
            actions_layout.addWidget(stop_btn)
        
        # View/Open button
        if self.file_type == 'image':
            view_btn = QPushButton()
            view_btn.setIcon(qta.icon('fa5s.eye', color='#3b82f6'))
            view_btn.setIconSize(QSize(16, 16))
            view_btn.setFixedSize(32, 32)
            view_btn.setToolTip('View Image')
            view_btn.setStyleSheet("""
                QPushButton {
                    background: #1f2937;
                    border: 1px solid #3b82f6;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background: #3b82f6;
                    border-color: #3b82f6;
                }
            """)
            view_btn.setCursor(Qt.PointingHandCursor)
            view_btn.clicked.connect(self._view_image)
            actions_layout.addWidget(view_btn)
        
        # Delete button
        delete_btn = QPushButton()
        delete_btn.setIcon(qta.icon('fa5s.trash', color='#ef4444'))
        delete_btn.setIconSize(QSize(16, 16))
        delete_btn.setFixedSize(32, 32)
        delete_btn.setToolTip('Delete File')
        delete_btn.setStyleSheet("""
            QPushButton {
                background: #1f2937;
                border: 1px solid #ef4444;
                border-radius: 5px;
            }
            QPushButton:hover {
                background: #ef4444;
                border-color: #ef4444;
            }
        """)
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(self._delete_file)
        actions_layout.addWidget(delete_btn)
        
        top_layout.addLayout(actions_layout)
        layout.addLayout(top_layout)
        
        # Audio player controls (only for audio files)
        if self.file_type == 'audio':
            player_widget = QWidget()
            player_widget.setStyleSheet("QWidget { background: transparent; }")
            player_layout = QVBoxLayout(player_widget)
            player_layout.setContentsMargins(0, 0, 0, 0)
            player_layout.setSpacing(4)
            
            # Time labels
            time_layout = QHBoxLayout()
            self.current_time_label = QLabel("00:00")
            self.current_time_label.setStyleSheet("""
                QLabel {
                    color: #10b981;
                    font-size: 10px;
                    font-family: 'Roboto', monospace;
                    font-weight: 700;
                }
            """)
            self.total_time_label = QLabel("00:00")
            self.total_time_label.setStyleSheet("""
                QLabel {
                    color: #9ca3af;
                    font-size: 10px;
                    font-family: 'Roboto', monospace;
                    font-weight: 700;
                }
            """)
            time_layout.addWidget(self.current_time_label)
            time_layout.addStretch()
            time_layout.addWidget(self.total_time_label)
            player_layout.addLayout(time_layout)
            
            # Seek slider
            self.seek_slider = QSlider(Qt.Horizontal)
            self.seek_slider.setMinimum(0)
            self.seek_slider.setMaximum(1000)
            self.seek_slider.setValue(0)
            self.seek_slider.setCursor(Qt.PointingHandCursor)
            self.seek_slider.setStyleSheet("""
                QSlider::groove:horizontal {
                    border: 1px solid #4b5563;
                    height: 4px;
                    background: #1f2937;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    background: #10b981;
                    border: 1px solid #34d399;
                    width: 12px;
                    height: 12px;
                    margin: -5px 0;
                    border-radius: 6px;
                }
                QSlider::handle:horizontal:hover {
                    background: #34d399;
                }
                QSlider::sub-page:horizontal {
                    background: #10b981;
                    border: 1px solid #4b5563;
                    height: 4px;
                    border-radius: 2px;
                }
            """)
            self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
            self.seek_slider.sliderReleased.connect(self._on_slider_released)
            player_layout.addWidget(self.seek_slider)
            
            layout.addWidget(player_widget)
            
            # Set total time if audio loaded
            if self.audio_data is not None and self.sample_rate:
                duration = len(self.audio_data) / self.sample_rate
                self.total_time_label.setText(self._format_time(duration))
    
    def _format_time(self, seconds):
        """Format seconds to MM:SS"""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
    
    def _on_slider_pressed(self):
        """User started dragging the slider"""
        self.is_seeking = True
        if self.is_playing:
            sd.stop()
    
    def _on_slider_released(self):
        """User finished dragging the slider"""
        self.is_seeking = False
        if self.audio_data is not None:
            # Seek to the new position
            seek_ratio = self.seek_slider.value() / 1000.0
            self.playback_position = int(seek_ratio * len(self.audio_data))
            
            if self.is_playing:
                # Continue playing from new position
                self._toggle_play()
                self._toggle_play()  # Stop then start to resume from new position
    
    def _update_playback_position(self):
        """Update playback position and slider"""
        if not self.is_seeking and self.is_playing and self.audio_data is not None:
            # Increment position
            samples_per_update = int(self.sample_rate * 0.1)
            self.playback_position = min(
                self.playback_position + samples_per_update,
                len(self.audio_data)
            )
            
            # Update slider and time
            if len(self.audio_data) > 0:
                progress = (self.playback_position / len(self.audio_data)) * 1000
                self.seek_slider.setValue(int(progress))
                
                current_time = self.playback_position / self.sample_rate
                self.current_time_label.setText(self._format_time(current_time))
            
            # Check if finished
            if self.playback_position >= len(self.audio_data):
                self._stop_audio()
    
    def _toggle_play(self):
        """Toggle play/pause audio"""
        if self.audio_data is None:
            return
        
        try:
            if self.is_playing:
                # Pause
                sd.stop()
                self.is_playing = False
                self.playback_timer.stop()
                self.play_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
                self.play_btn.setToolTip('Play Audio')
            else:
                # Play from current position
                sd.stop()
                audio_to_play = self.audio_data[self.playback_position:]
                sd.play(audio_to_play, self.sample_rate)
                self.is_playing = True
                self.playback_timer.start(100)
                self.play_btn.setIcon(qta.icon('fa5s.pause', color='#f59e0b'))
                self.play_btn.setToolTip('Pause Audio')
        except Exception as e:
            print(f"Error toggling playback: {e}")
    
    def _stop_audio(self):
        """Stop audio playback"""
        try:
            sd.stop()
            self.is_playing = False
            self.playback_position = 0
            self.playback_timer.stop()
            self.seek_slider.setValue(0)
            self.current_time_label.setText("00:00")
            self.play_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
            self.play_btn.setToolTip('Play Audio')
        except Exception as e:
            print(f"Error stopping audio: {e}")
    
    def _view_image(self):
        """Open image in default viewer"""
        if self.file_type == 'image':
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.file_path))
    
    def _delete_file(self):
        """Delete the file"""
        reply = QMessageBox.question(
            self,
            "Delete File",
            f"Are you sure you want to delete this file?\n\n{Path(self.file_path).name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                os.remove(self.file_path)
                # Find the dropdown widget parent
                parent = self.parent()
                while parent and not isinstance(parent, AttachmentsDropdownWidget):
                    parent = parent.parent()
                if parent:
                    parent.remove_item(self)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete file: {str(e)}")


class AttachmentsDropdownWidget(QWidget):
    """Dropdown widget showing saved attachments"""
    
    def __init__(self, study_uid, file_type, parent=None):
        super().__init__(parent)
        self.study_uid = study_uid
        self.file_type = file_type  # 'audio' or 'image'
        self.attachment_items = []
        
        self._setup_ui()
        self._load_attachments()
        
        # Close when clicking outside
        self.setAttribute(Qt.WA_DeleteOnClose)
    
    def _setup_ui(self):
        """Setup dropdown UI"""
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("""
            QWidget {
                background: #1f2937;
                border: 1px solid #4b5563;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Header
        header_label = QLabel(f"{'📷 Captured Images' if self.file_type == 'image' else '🎙️ Audio Recordings'}")
        header_label.setStyleSheet("""
            QLabel {
                color: #f3f4f6;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Roboto', sans-serif;
                padding: 4px;
            }
        """)
        layout.addWidget(header_label)
        
        # Scroll area for items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #1f2937;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #4b5563;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6b7280;
            }
        """)
        
        self.container = QWidget()
        self.container.setStyleSheet("QWidget { background: transparent; }")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(8)
        self.container_layout.addStretch()
        
        scroll.setWidget(self.container)
        layout.addWidget(scroll)
    
    def _load_attachments(self):
        """Load attachments from folder"""
        # Clear existing items
        for item in self.attachment_items:
            item.deleteLater()
        self.attachment_items.clear()
        
        # Get attachment path
        attachment_dir = ATTACHMENT_PATH / self.study_uid
        if not attachment_dir.exists():
            self._show_empty_state()
            return
        
        # Get files
        if self.file_type == 'audio':
            files = list(attachment_dir.glob('*.wav'))
        else:
            files = list(attachment_dir.glob('*.png')) + list(attachment_dir.glob('*.jpg'))
        
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not files:
            self._show_empty_state()
            return
        
        # Add items
        for file_path in files:
            item = AttachmentItemWidget(str(file_path), self.file_type, self.container)
            self.container_layout.insertWidget(self.container_layout.count() - 1, item)
            self.attachment_items.append(item)
    
    def _show_empty_state(self):
        """Show empty state message"""
        empty_label = QLabel(f"No {self.file_type}s found")
        empty_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                padding: 20px;
            }
        """)
        empty_label.setAlignment(Qt.AlignCenter)
        self.container_layout.insertWidget(0, empty_label)
    
    def remove_item(self, item):
        """Remove an item from the list"""
        if item in self.attachment_items:
            self.attachment_items.remove(item)
            item.deleteLater()
        
        # Reload to refresh list
        self._load_attachments()
    
    def showEvent(self, event):
        """Reload attachments when shown"""
        super().showEvent(event)
        self._load_attachments()
    
    def mousePressEvent(self, event):
        """Close dropdown when clicking outside"""
        if not self.geometry().contains(event.pos()):
            self.close()
        super().mousePressEvent(event)

