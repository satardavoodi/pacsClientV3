# attachments_dropdown.py — fully decoupled panels for image & audio
from __future__ import annotations
import asyncio
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Iterable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QMessageBox, QSlider, QFrame
)
from PySide6.QtCore import Qt, QSize, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices, QIcon
import qtawesome as qta

from PacsClient.utils.config import ATTACHMENT_PATH, ICON_PATH


# ============================================================
# Image Panel (fully self-contained)
# ============================================================
class ImageAttachmentsPanel(QWidget):
    IMAGE_EXTS: Iterable[str] = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")

    def __init__(self, study_uid: str, parent: Optional[QWidget] = None,
                 method_update_counter: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.study_uid = study_uid
        self.method_update_counter = method_update_counter
        self.items: list[QWidget] = []

        self._build_ui()
        self._load_files()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(10, 10, 10, 10)
        self._root.setSpacing(10)

        header = QLabel("📷 Captured Images")
        header.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 15px;
                font-weight: 700;
                font-family: 'Roboto', sans-serif;
                padding: 8px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #2563eb);
                border-radius: 6px;
                margin-bottom: 4px;
            }
        """)
        self._root.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea { border:none; background:transparent; }
            QScrollBar:vertical { background:#1f2937; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical { background:#4b5563; border-radius:5px; }
            QScrollBar::handle:vertical:hover { background:#6b7280; }
        """)
        self._container = QWidget()
        self._container.setStyleSheet("QWidget { background:transparent; }")
        self._c_layout = QVBoxLayout(self._container)
        self._c_layout.setContentsMargins(0, 0, 0, 0)
        self._c_layout.setSpacing(8)
        self._c_layout.addStretch()
        self._scroll.setWidget(self._container)
        self._root.addWidget(self._scroll)

    # ---------------- Data ----------------
    def _iter_files(self) -> list[Path]:
        attach_dir = ATTACHMENT_PATH / self.study_uid
        if not attach_dir.exists():
            return []
        files: list[Path] = []
        for ext in self.IMAGE_EXTS:
            files.extend(attach_dir.glob(f"*{ext}"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _load_files(self):
        for w in self.items:
            w.deleteLater()
        self.items.clear()

        files = self._iter_files()
        if not files:
            empty = QLabel("No images found")
            empty.setStyleSheet("QLabel { color:#9ca3af; font-size:13px; padding:20px; }")
            empty.setAlignment(Qt.AlignCenter)
            self._c_layout.insertWidget(0, empty)
            self.items.append(empty)
            return

        for idx, fp in enumerate(files, start=1):
            item = self._ImageItem(str(fp), self, idx)
            self._c_layout.insertWidget(self._c_layout.count()-1, item)
            self.items.append(item)

    # ---------------- Item ----------------
    class _ImageItem(QWidget):
        def __init__(self, file_path: str, panel: 'ImageAttachmentsPanel', index: int = 0):
            super().__init__(panel)
            self._panel = panel
            self._file_path = file_path
            self._index = index
            self._build_ui()

        def _build_ui(self):
            self.setFixedHeight(110)
            self.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #2d3748);
                    border-radius: 8px;
                    border: 1px solid #4b5563;
                }
                QWidget:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4b5563, stop:1 #374151);
                    border-color: #60a5fa;
                }
            """)
            root = QVBoxLayout(self)
            root.setContentsMargins(8, 8, 8, 8)
            root.setSpacing(6)

            # Top: Thumbnail با دکمه‌های کوچک در گوشه
            top_row = QHBoxLayout()
            top_row.setSpacing(8)
            
            # Thumbnail container with overlay buttons
            thumb_container = QWidget()
            thumb_container.setFixedSize(80, 80)
            thumb_layout = QVBoxLayout(thumb_container)
            thumb_layout.setContentsMargins(0, 0, 0, 0)
            thumb_layout.setSpacing(0)
            
            thumb = QLabel()
            thumb.setFixedSize(80, 80)
            thumb.setStyleSheet("""
                QLabel {
                    background: #1f2937;
                    border: 2px solid #4b5563;
                    border-radius: 6px;
                }
            """)
            thumb.setAlignment(Qt.AlignCenter)
            try:
                pix = QPixmap(self._file_path)
                if pix.isNull():
                    icon = qta.icon('fa5s.image', color='#3b82f6', scale_factor=2.0)
                    thumb.setPixmap(icon.pixmap(QSize(40, 40)))
                else:
                    # حفظ aspect ratio - عکس کش نمی‌شود
                    scaled_pix = pix.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    thumb.setPixmap(scaled_pix)
            except Exception:
                icon = qta.icon('fa5s.image', color='#3b82f6', scale_factor=2.0)
                thumb.setPixmap(icon.pixmap(QSize(40, 40)))
            thumb_layout.addWidget(thumb)
            
            top_row.addWidget(thumb_container)
            
            # Info + Actions
            info_actions = QVBoxLayout()
            info_actions.setSpacing(4)
            
            # شماره ردیف + تاریخ
            info_row = QHBoxLayout()
            info_row.setSpacing(8)
            
            # شماره ردیف
            index_lbl = QLabel(f"#{self._index}")
            index_lbl.setStyleSheet("""
                QLabel {
                    color: #60a5fa;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                }
            """)
            info_row.addWidget(index_lbl)
            
            # تاریخ
            date_lbl = QLabel(self._fmt_mtime(self._file_path))
            date_lbl.setStyleSheet("""
                QLabel {
                    color: #9ca3af;
                    font-size: 11px;
                    font-weight: 400;
                    font-family: 'Roboto', sans-serif;
                }
            """)
            info_row.addWidget(date_lbl)
            info_row.addStretch()
            
            info_actions.addLayout(info_row)
            info_actions.addStretch()
            
            # Action buttons - افقی و کوچک
            actions = QHBoxLayout()
            actions.setSpacing(4)
            
            view_btn = QPushButton()
            view_btn.setIcon(qta.icon('fa5s.eye', color='#ffffff'))
            view_btn.setIconSize(QSize(14, 14))
            view_btn.setFixedSize(28, 28)
            view_btn.setToolTip('View Image')
            view_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #3b82f6, stop:1 #2563eb);
                    border: 1px solid #3b82f6;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background: #60a5fa;
                    border-color: #60a5fa;
                }
            """)
            view_btn.setCursor(Qt.PointingHandCursor)
            view_btn.clicked.connect(self._open_file)
            actions.addWidget(view_btn)

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon('fa5s.trash', color='#ffffff'))
            del_btn.setIconSize(QSize(14, 14))
            del_btn.setFixedSize(28, 28)
            del_btn.setToolTip('Delete')
            del_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    border: 1px solid #ef4444;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background: #f87171;
                    border-color: #f87171;
                }
            """)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(self._delete)
            actions.addWidget(del_btn)
            
            actions.addStretch()
            info_actions.addLayout(actions)
            
            top_row.addLayout(info_actions, 1)
            root.addLayout(top_row)

        def _open_file(self):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._file_path))

        def _delete(self):
            reply = QMessageBox.question(
                self, "Delete File",
                f"Are you sure you want to delete this file?\n\n{Path(self._file_path).name}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    os.remove(self._file_path)
                    if callable(self._panel.method_update_counter):
                        self._panel.method_update_counter()
                    self._panel._load_files()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not delete file: {e}")

        @staticmethod
        def _fmt_mtime(fp: str | Path) -> str:
            try:
                ts = os.path.getmtime(str(fp))
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M")
            except Exception:
                return "Unknown"


# ============================================================
# Audio Panel (fully self-contained)
# ============================================================
class AudioAttachmentsPanel(QWidget):
    AUDIO_EXTS: Iterable[str] = (".wav", ".mp3", ".m4a", ".ogg", ".webm")

    def __init__(self, study_uid: str, parent: Optional[QWidget] = None,
                 method_update_counter: Optional[Callable[[], None]] = None,
                 method_open_report: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.study_uid = study_uid
        self.method_update_counter = method_update_counter
        self.method_open_report = method_open_report
        self.items: list[QWidget] = []

        self._build_ui()
        self._load_files()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(10, 10, 10, 10)
        self._root.setSpacing(10)

        header = QLabel("🎙️ Audio Recordings")
        header.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 15px;
                font-weight: 700;
                font-family: 'Roboto', sans-serif;
                padding: 8px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #10b981, stop:1 #059669);
                border-radius: 6px;
                margin-bottom: 4px;
            }
        """)
        self._root.addWidget(header)

        self._scroll = QScrollArea(); self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea { border:none; background:transparent; }
            QScrollBar:vertical { background:#1f2937; width:10px; border-radius:5px; }
            QScrollBar::handle:vertical { background:#4b5563; border-radius:5px; }
            QScrollBar::handle:vertical:hover { background:#6b7280; }
        """)
        self._container = QWidget()
        self._container.setStyleSheet("QWidget { background:transparent; }")
        self._c_layout = QVBoxLayout(self._container)
        self._c_layout.setContentsMargins(0, 0, 0, 0)
        self._c_layout.setSpacing(8)
        self._c_layout.addStretch()
        self._scroll.setWidget(self._container)
        self._root.addWidget(self._scroll)

    # ---------------- Data ----------------
    def _iter_files(self) -> list[Path]:
        attach_dir = ATTACHMENT_PATH / self.study_uid
        if not attach_dir.exists():
            return []
        files: list[Path] = []
        for ext in self.AUDIO_EXTS:
            files.extend(attach_dir.glob(f"*{ext}"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def _load_files(self):
        for w in self.items:
            w.deleteLater()
        self.items.clear()

        files = self._iter_files()
        if not files:
            empty = QLabel("No audios found")
            empty.setStyleSheet("QLabel { color:#9ca3af; font-size:13px; padding:20px; }")
            empty.setAlignment(Qt.AlignCenter)
            self._c_layout.insertWidget(0, empty)
            self.items.append(empty)
            return

        for idx, fp in enumerate(files, start=1):
            item = self._AudioItem(str(fp), self, idx)
            self._c_layout.insertWidget(self._c_layout.count()-1, item)
            self.items.append(item)

    # ---------------- Item ----------------
    class _AudioItem(QWidget):
        def __init__(self, file_path: str, panel: 'AudioAttachmentsPanel', index: int = 0):
            super().__init__(panel)
            # lazy imports only inside audio branch
            global sd, sf, np
            import sounddevice as sd  # noqa: F401
            import soundfile as sf    # noqa: F401
            import numpy as np        # noqa: F401

            self._panel = panel
            self._file_path = file_path
            self._index = index

            # state
            self._is_playing = False
            self._audio_data = None
            self._sr = None
            self._pos = 0
            self._seeking = False
            self._pending_duration: Optional[float] = None

            # ui refs
            self._play_btn: Optional[QPushButton] = None
            self._slider: Optional[QSlider] = None
            self._cur_lbl: Optional[QLabel] = None
            self._tot_lbl: Optional[QLabel] = None

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)

            self._build_ui()   # build first
            self._load_audio_meta()  # cheap header read for duration; full samples load lazily on first play (avoids UI stall)

        def _build_ui(self):
            self.setFixedHeight(140)
            self.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #2d3748);
                    border-radius: 8px;
                    border: 1px solid #4b5563;
                }
                QWidget:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4b5563, stop:1 #374151);
                    border-color: #10b981;
                }
            """)
            root = QVBoxLayout(self)
            root.setContentsMargins(8, 6, 8, 6)
            root.setSpacing(6)

            # top row
            top = QHBoxLayout(); top.setSpacing(10)

            # mic box
            mic_box = QWidget(); mic_box.setFixedWidth(60)
            mic_box.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #064e3b, stop:0.5 #059669, stop:1 #064e3b);
                    border: 2px solid #10b981; border-radius: 6px;
                }
            """)
            mv = QVBoxLayout(mic_box); mv.setAlignment(Qt.AlignCenter)
            mic_icon = QLabel()
            mic_icon.setPixmap(qta.icon('fa5s.microphone', color='#34d399', scale_factor=1.5).pixmap(QSize(30, 30)))
            mic_icon.setAlignment(Qt.AlignCenter)
            mv.addWidget(mic_icon)
            top.addWidget(mic_box, 0)

            # Info: شماره ردیف + تاریخ
            info_col = QVBoxLayout(); info_col.setSpacing(2)
            
            # شماره ردیف
            index_lbl = QLabel(f"#{self._index}")
            index_lbl.setStyleSheet("QLabel { color:#10b981; font-size:16px; font-weight:700; font-family:'Roboto', sans-serif; }")
            info_col.addWidget(index_lbl)
            
            # تاریخ
            date_lbl = QLabel(self._fmt_mtime(self._file_path))
            date_lbl.setStyleSheet("QLabel { color:#9ca3af; font-size:11px; font-weight:400; font-family:'Roboto', sans-serif; }")
            info_col.addWidget(date_lbl)
            info_col.addStretch()
            
            top.addLayout(info_col, 1)
            root.addLayout(top)

            # player
            player = QWidget(); pv = QVBoxLayout(player); pv.setContentsMargins(0,0,0,0); pv.setSpacing(4)
            player.setStyleSheet("QWidget { background: transparent; border: none; }")

            times = QHBoxLayout()
            self._cur_lbl = QLabel("00:00"); self._cur_lbl.setStyleSheet(self._time_css("#10b981"))
            self._tot_lbl = QLabel("00:00"); self._tot_lbl.setStyleSheet(self._time_css("#9ca3af"))
            times.addWidget(self._cur_lbl); times.addStretch(); times.addWidget(self._tot_lbl)
            pv.addLayout(times)

            self._slider = QSlider(Qt.Horizontal); self._slider.setRange(0, 1000); self._slider.setValue(0)
            self._slider.setCursor(Qt.PointingHandCursor)
            self._slider.setStyleSheet(self._slider_css())
            self._slider.sliderPressed.connect(self._on_press)
            self._slider.sliderReleased.connect(self._on_release)
            pv.addWidget(self._slider)
            # if duration was computed earlier, apply now
            if self._pending_duration is not None:
                self._tot_lbl.setText(self._fmt_time(self._pending_duration))
                self._pending_duration = None
            root.addWidget(player)

            # Actions - با استایل بهتر و spacing مناسب
            acts = QHBoxLayout()
            acts.setSpacing(6)

            self._play_btn = QPushButton()
            self._play_btn.setIcon(qta.icon('fa5s.play', color='#ffffff'))
            self._play_btn.setIconSize(QSize(16, 16))
            self._play_btn.setFixedSize(36, 36)
            self._play_btn.setToolTip('Play Audio')
            self._play_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #10b981, stop:1 #059669);
                    border: 1px solid #10b981;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #34d399, stop:1 #10b981);
                    border-color: #34d399;
                }
                QPushButton:pressed {
                    background: #059669;
                }
            """)
            self._play_btn.setCursor(Qt.PointingHandCursor)
            self._play_btn.clicked.connect(self._toggle)
            acts.addWidget(self._play_btn)

            stop_btn = QPushButton()
            stop_btn.setIcon(qta.icon('fa5s.stop', color='#ffffff'))
            stop_btn.setIconSize(QSize(16, 16))
            stop_btn.setFixedSize(36, 36)
            stop_btn.setToolTip('Stop Audio')
            stop_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f87171, stop:1 #ef4444);
                    border-color: #f87171;
                }
                QPushButton:pressed {
                    background: #dc2626;
                }
            """)
            stop_btn.setCursor(Qt.PointingHandCursor)
            stop_btn.clicked.connect(self._stop)
            acts.addWidget(stop_btn)

            report_btn = QPushButton()
            report_btn.setIcon(QIcon(f'{ICON_PATH}/report.png'))
            report_btn.setIconSize(QSize(16, 16))
            report_btn.setFixedSize(36, 36)
            report_btn.setToolTip('ECHO MIND - Report')
            report_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #8b5cf6, stop:1 #7c3aed);
                    border: 1px solid #8b5cf6;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #a78bfa, stop:1 #8b5cf6);
                    border-color: #a78bfa;
                }
                QPushButton:pressed {
                    background: #7c3aed;
                }
            """)
            report_btn.setCursor(Qt.PointingHandCursor)
            report_btn.clicked.connect(self._open_report)
            acts.addWidget(report_btn)

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon('fa5s.trash', color='#ffffff'))
            del_btn.setIconSize(QSize(16, 16))
            del_btn.setFixedSize(36, 36)
            del_btn.setToolTip('Delete File')
            del_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #ef4444, stop:1 #dc2626);
                    border: 1px solid #ef4444;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f87171, stop:1 #ef4444);
                    border-color: #f87171;
                }
                QPushButton:pressed {
                    background: #dc2626;
                }
            """)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(self._delete)
            acts.addWidget(del_btn)

            root.addLayout(acts)

        # ---- audio logic ----
        def _load_audio_meta(self):
            """Header-only read: fills the duration label without decoding the
            whole file on the UI thread. Full samples load lazily on first use
            (_ensure_audio_loaded), removing a multi-second main-thread stall."""
            try:
                import soundfile as sf
                info = sf.info(self._file_path)
                self._sr = int(info.samplerate)
                duration = float(info.duration)
                if self._tot_lbl is not None:
                    self._tot_lbl.setText(self._fmt_time(duration))
                else:
                    self._pending_duration = duration
            except Exception as e:
                print(f"[Audio] Error reading header: {e}")

        def _ensure_audio_loaded(self):
            """Decode full samples on demand (first play/seek). True if ready."""
            if self._audio_data is not None:
                return True
            self._load_audio()
            return self._audio_data is not None

        def _load_audio(self):
            try:
                import soundfile as sf
                data, sr = sf.read(self._file_path, always_2d=False)
                self._audio_data = data
                self._sr = int(sr)
                if self._audio_data is not None and self._sr:
                    total_len = self._audio_data.shape[0] if hasattr(self._audio_data, "shape") else len(self._audio_data)
                    duration = total_len / self._sr
                    if self._tot_lbl is not None:
                        self._tot_lbl.setText(self._fmt_time(duration))
                    else:
                        self._pending_duration = duration
            except Exception as e:
                print(f"[Audio] Error loading: {e}")
                self._audio_data, self._sr = None, None

        def _toggle(self):
            if not self._is_playing and not self._ensure_audio_loaded():
                return
            if self._audio_data is None or not self._sr:
                return
            try:
                import sounddevice as sd
                if self._is_playing:
                    sd.stop()
                    self._is_playing = False
                    self._timer.stop()
                    self._play_btn.setIcon(qta.icon('fa5s.play', color='#ffffff'))
                    self._play_btn.setToolTip('Play Audio')
                else:
                    sd.stop()
                    audio_to_play = self._audio_data[self._pos:]
                    sd.play(audio_to_play, self._sr)
                    self._is_playing = True
                    self._timer.start(100)
                    self._play_btn.setIcon(qta.icon('fa5s.pause', color='#ffffff'))
                    self._play_btn.setToolTip('Pause Audio')
            except Exception as e:
                print(f"[Audio] toggle error: {e}")

        def _stop(self):
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            self._is_playing = False
            self._pos = 0
            self._timer.stop()
            if self._slider:
                self._slider.setValue(0)
            if self._cur_lbl:
                self._cur_lbl.setText("00:00")
            if self._play_btn:
                self._play_btn.setIcon(qta.icon('fa5s.play', color='#ffffff'))
                self._play_btn.setToolTip('Play Audio')

        def _tick(self):
            if not (self._is_playing and self._audio_data is not None and self._sr and not self._seeking):
                return
            total_len = self._audio_data.shape[0] if hasattr(self._audio_data, "shape") else len(self._audio_data)
            step = int(self._sr * 0.1)
            self._pos = min(self._pos + step, total_len)
            if total_len > 0 and self._slider:
                self._slider.setValue(int((self._pos / total_len) * 1000))
            if self._cur_lbl:
                self._cur_lbl.setText(self._fmt_time(self._pos / self._sr))
            if self._pos >= total_len:
                self._stop()

        def _on_press(self):
            self._seeking = True
            if self._is_playing:
                try:
                    import sounddevice as sd
                    sd.stop()
                except Exception:
                    pass

        def _on_release(self):
            self._seeking = False
            self._ensure_audio_loaded()
            if self._audio_data is None or not self._sr:
                return
            seek_ratio = self._slider.value() / 1000.0
            total_len = self._audio_data.shape[0] if hasattr(self._audio_data, "shape") else len(self._audio_data)
            self._pos = int(seek_ratio * total_len)
            if self._is_playing:
                self._toggle(); self._toggle()

        def _open_report(self):
            cb = self._panel.method_open_report
            if callable(cb):
                try:
                    asyncio.create_task(cb(self._file_path))
                except RuntimeError:
                    cb(self._file_path)

        def _delete(self):
            reply = QMessageBox.question(
                self, "Delete File",
                f"Are you sure you want to delete this file?\n\n{Path(self._file_path).name}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    os.remove(self._file_path)
                    if callable(self._panel.method_update_counter):
                        self._panel.method_update_counter()
                    self._panel._load_files()
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Could not delete file: {e}")

        @staticmethod
        def _fmt_time(sec: float) -> str:
            mins = int(sec // 60); secs = int(sec % 60)
            return f"{mins:02d}:{secs:02d}"

        @staticmethod
        def _fmt_mtime(fp: str | Path) -> str:
            try:
                ts = os.path.getmtime(str(fp))
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d  %H:%M:%S")
            except Exception:
                return "Unknown"

        @staticmethod
        def _time_css(color: str) -> str:
            return f"""
                QLabel {{
                    color: {color}; font-size:10px; font-family:'Roboto', monospace;
                    font-weight:700; background:transparent; border:none; padding:2px 4px;
                }}
            """
            # QScrollArea { border:none; background:transparent; }

        @staticmethod
        def _slider_css() -> str:
            return """
            QSlider::groove:horizontal { border:1px solid #4b5563; height:4px; background:#1f2937; border-radius:2px; }
            QSlider::handle:horizontal { background:#10b981; border:1px solid #34d399; width:12px; height:12px; margin:-5px 0; border-radius:6px; }
            QSlider::handle:horizontal:hover { background:#34d399; }
            QSlider::sub-page:horizontal { background:#10b981; border:1px solid #4b5563; height:4px; border-radius:2px; }
            """


# ============================================================
# Dropdown wrapper (parent only picks panel & shows popup)
# ============================================================
class AttachmentsDropdownWidget(QWidget):
    """
    Parent only decides **which panel** to instantiate and hosts it.
    No item/file management logic lives here.
    """

    def __init__(self,
                 study_uid: str,
                 file_type: str,  # 'audio' | 'image'
                 parent: Optional[QWidget] = None,
                 method_update_counter: Optional[Callable[[], None]] = None,
                 method_open_report: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
                border: 2px solid #374151;
                border-radius: 10px;
            }
        """)
        self.setAttribute(Qt.WA_DeleteOnClose)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        file_type = (file_type or "").lower().strip()
        if file_type == "audio":
            panel = AudioAttachmentsPanel(
                study_uid,
                self,
                method_update_counter=method_update_counter,
                method_open_report=method_open_report
            )
        else:
            panel = ImageAttachmentsPanel(
                study_uid,
                self,
                method_update_counter=method_update_counter
            )

        root.addWidget(panel)

    def mousePressEvent(self, event):
        if not self.rect().contains(event.pos()):
            self.close()
        super().mousePressEvent(event)
