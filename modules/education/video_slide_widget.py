"""Video player widget for presentation slides."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QStyle
)
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from pathlib import Path


class VideoSlideWidget(QWidget):
    """Widget for displaying video in presentation."""
    
    playback_finished = Signal()
    
    def __init__(self, video_path, autoplay=False, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.autoplay = autoplay
        self.setup_ui()
        self.load_video()
    
    def setup_ui(self):
        """Setup the video player UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Video widget
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("""
            QVideoWidget {
                background-color: #000000;
                border-radius: 5px;
            }
        """)
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
        controls_widget = QWidget()
        controls_widget.setStyleSheet("""
            QWidget {
                background-color: #2d3748;
                border-radius: 5px;
            }
        """)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(10, 5, 10, 5)
        controls_layout.setSpacing(5)
        
        # Progress slider
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderMoved.connect(self.set_position)
        self.progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #4a5568;
                height: 6px;
                background: #374151;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3182ce;
                border: 1px solid #2c5aa0;
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #3182ce;
                border-radius: 3px;
            }
        """)
        controls_layout.addWidget(self.progress_slider)
        
        # Buttons and time display
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # Play/Pause button
        self.play_pause_btn = QPushButton()
        self.play_pause_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_btn.setFixedSize(40, 40)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        self.play_pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
        """)
        buttons_layout.addWidget(self.play_pause_btn)
        
        # Stop button
        self.stop_btn = QPushButton()
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.clicked.connect(self.stop_video)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                border: none;
                border-radius: 20px;
            }
            QPushButton:hover {
                background-color: #c53030;
            }
        """)
        buttons_layout.addWidget(self.stop_btn)
        
        # Time labels
        self.time_label = QLabel("00:00")
        self.time_label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        buttons_layout.addWidget(self.time_label)
        
        self.duration_label = QLabel("/ 00:00")
        self.duration_label.setStyleSheet("color: #a0aec0;")
        buttons_layout.addWidget(self.duration_label)
        
        buttons_layout.addStretch()
        
        # Volume slider
        volume_label = QLabel("Volume:")
        volume_label.setStyleSheet("color: #e2e8f0;")
        buttons_layout.addWidget(volume_label)
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self.change_volume)
        self.volume_slider.setStyleSheet(self.progress_slider.styleSheet())
        buttons_layout.addWidget(self.volume_slider)
        
        controls_layout.addLayout(buttons_layout)
        layout.addWidget(controls_widget)
    
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
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setStyleSheet("""
            QLabel {
                color: #e53e3e;
                font-size: 12pt;
                font-weight: bold;
                background-color: #2d3748;
                padding: 20px;
                border-radius: 5px;
            }
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
        self.setup_ui()
        self.load_video()
    
    def setup_ui(self):
        """Setup simple video display."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: #000000;")
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
