"""Video player widget for presentation slides."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QStyle
)
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from pathlib import Path

from PacsClient.utils.theme_manager import get_theme_manager


class VideoSlideWidget(QWidget):
    """Widget for displaying video in presentation."""
    
    playback_finished = Signal()
    
    def __init__(self, video_path, autoplay=False, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.autoplay = autoplay
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        self.setup_ui()
        self.load_video()
    
    def _on_theme_changed(self, theme):
        """Handle theme changes."""
        self._theme = theme or self.theme_manager.current_theme()
        self._apply_theme_styles()
    
    def setup_ui(self):
        """Setup the video player UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Video widget
        self.video_widget = QVideoWidget()
        self.video_widget.storeVideoWidget = True
        layout.addWidget(self.video_widget, stretch=1)
        
        # Media player setup
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        
        # Connect signals
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        self.player.mediaStatusChanged.connect(self.handle_media_status)
        self.player.errorOccurred.connect(self.handle_error)
        
        # Controls panel
        self.controls_widget = QWidget()
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(10, 5, 10, 5)
        controls_layout.setSpacing(5)
        
        # Progress slider
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderMoved.connect(self.set_position)
        controls_layout.addWidget(self.progress_slider)
        
        # Buttons and time display
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Play/Pause button
        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setFixedSize(40, 40)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        buttons_layout.addWidget(self.play_pause_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.clicked.connect(self.stop_video)
        buttons_layout.addWidget(self.stop_btn)
        
        # Time labels
        self.time_label = QLabel("00:00")
        buttons_layout.addWidget(self.time_label)
        
        self.duration_label = QLabel("/ 00:00")
        buttons_layout.addWidget(self.duration_label)
        
        buttons_layout.addStretch()
        
        # Volume slider
        volume_label = QLabel("Volume:")
        buttons_layout.addWidget(volume_label)
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.change_volume)
        buttons_layout.addWidget(self.volume_slider)
        
        controls_layout.addLayout(buttons_layout)
        layout.addWidget(self.controls_widget)
        
        self._apply_theme_styles()
    
    def _apply_theme_styles(self):
        """Apply theme-based styling to all UI elements."""
        t = self._theme
        
        # Video widget - deep background
        self.video_widget.setStyleSheet(f"""
            QVideoWidget {{
                background-color: {t['panel_deep_bg']};
                border-radius: 5px;
            }}
        """)
        
        # Controls widget background
        self.controls_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {t['panel_alt_bg']};
                border-radius: 5px;
            }}
        """)
        
        # Progress slider
        self.progress_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid {t['border']};
                height: 6px;
                background: {t['panel_bg']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {t['accent']};
                border: 1px solid {t['accent_hover']};
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {t['accent']};
                border-radius: 3px;
            }}
        """)
        
        # Play/Pause button
        self.play_pause_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                border: none;
                border-radius: 20px;
                color: {t['button_text']};
            }}
            QPushButton:hover {{
                background-color: {t['accent_hover']};
            }}
        """)
        
        # Stop button (danger/error color)
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['danger']};
                border: none;
                border-radius: 20px;
                color: {t['button_text']};
            }}
            QPushButton:hover {{
                background-color: {t['warning']};
            }}
        """)
        
        # Time label
        self.time_label.setStyleSheet(f"color: {t['text_primary']}; font-weight: bold;")
        
        # Duration label (muted)
        self.duration_label.setStyleSheet(f"color: {t['text_secondary']};")
        
        # Volume label
        volume_label = None
        for widget in self.findChildren(QLabel):
            if widget.text() == "Volume:":
                volume_label = widget
                break
        if volume_label:
            volume_label.setStyleSheet(f"color: {t['text_primary']};")
        
        # Volume slider
        self.volume_slider.setStyleSheet(self.progress_slider.styleSheet())
    
    def load_video(self):
        """Load the video file."""
        if not Path(self.video_path).exists():
            self.show_error(f"Video file not found: {self.video_path}")
            return
        
        url = QUrl.fromLocalFile(self.video_path)
        self.player.setSource(url)
        
        # Set initial volume
        self.audio_output.setVolume(self.volume_slider.value() / 100.0)
        
        if self.autoplay:
            self.player.play()
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
    
    def toggle_play_pause(self):
        """Toggle between play and pause."""
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.player.play()
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
    
    def stop_video(self):
        """Stop video playback."""
        self.player.stop()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.progress_slider.setValue(0)
    
    def set_position(self, position):
        """Set playback position."""
        self.player.setPosition(position)
    
    def position_changed(self, position):
        """Handle position change."""
        self.progress_slider.setValue(position)
        self.time_label.setText(self.format_time(position))
    
    def duration_changed(self, duration):
        """Handle duration change."""
        self.progress_slider.setRange(0, duration)
        self.duration_label.setText(f"/ {self.format_time(duration)}")
    
    def change_volume(self, value):
        """Change volume."""
        self.audio_output.setVolume(value / 100.0)
    
    def handle_media_status(self, status):
        """Handle media status changes."""
        if status == QMediaPlayer.EndOfMedia:
            self.playback_finished.emit()
            self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
    
    def handle_error(self, error, error_string):
        """Handle playback errors."""
        self.show_error(f"Playback error: {error_string}")
    
    def show_error(self, message):
        """Show error message."""
        t = self._theme
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet(f"""
            QLabel {{
                color: {t['danger']};
                font-size: 12pt;
                font-weight: bold;
                background-color: {t['panel_alt_bg']};
                padding: 20px;
                border-radius: 5px;
            }}
        """)
        # Replace video widget with error label
        self.layout().replaceWidget(self.video_widget, error_label)
        self.video_widget.deleteLater()
    
    @staticmethod
    def format_time(ms):
        """Format milliseconds to MM:SS."""
        seconds = ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def cleanup(self):
        """Cleanup resources when widget is destroyed."""
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())


class SimpleVideoWidget(QWidget):
    """Simplified video widget without controls for presentation mode."""
    
    def __init__(self, video_path, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.setup_ui()
        self.load_video()
    
    def setup_ui(self):
        """Setup simple video display."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        t = self._theme
        self.video_widget.setStyleSheet(f"background-color: {t['panel_deep_bg']};")
        layout.addWidget(self.video_widget)
        
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.audio_output.setVolume(0.7)
    
    def load_video(self):
        """Load and play video."""
        if Path(self.video_path).exists():
            url = QUrl.fromLocalFile(self.video_path)
            self.player.setSource(url)
    
    def play(self):
        """Start playback."""
        self.player.play()
    
    def pause(self):
        """Pause playback."""
        self.player.pause()
    
    def stop(self):
        """Stop playback."""
        self.player.stop()
    
    def cleanup(self):
        """Cleanup resources."""
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
