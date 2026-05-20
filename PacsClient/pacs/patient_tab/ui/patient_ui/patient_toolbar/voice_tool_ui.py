from __future__ import annotations

import asyncio
import os
import queue
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import Qt, QTimer, QRect, QEvent, Signal
from PySide6.QtGui import QPainter, QPen, QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMessageBox, QApplication
)

# مهم: مسیر ذخیره را از کانفیگ پروژه بگیر
try:
    from PacsClient.utils.config import ATTACHMENT_PATH
except Exception:
    ATTACHMENT_PATH = Path.cwd() / "attachment"


class VoiceWidget(QWidget):
    """
    ویجت ضبط صدا که دقیقا زیر دکمه میکروفون در تولبار نمایش داده می‌شود.
    - هیچ آپلودی به سرور انجام نمی‌دهد
    - فایل را به صورت WAV در فولدر ATTACHMENT_PATH / study_uid ذخیره می‌کند
    """

    def __init__(self, patient_widget: QWidget, method_update_audio_counter, 
                 method_check_status_mic_btn, method_sync=None):
        super().__init__(patient_widget)
        self.patient_widget = patient_widget
        self.method_update_audio_counter = method_update_audio_counter
        self.method_check_status_mic_btn = method_check_status_mic_btn
        self.method_sync = method_sync
        self._inline_mode = False
        
        # 🔹 تنظیمات پنجره برای ماندگاری و عدم پرش
        self.setWindowFlags(
            Qt.Dialog |  # Dialog برای ماندگاری بهتر
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(380)
        
        # 🔹 مهم: غیرفعال کردن بسته شدن با کلیک خارج
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        
        # اتصال به پنجره اصلی برای کنترل Alt+Tab و بسته‌شدن برنامه
        self._main_window = self.patient_widget.window()
        if self._main_window is not None:
            self._main_window.installEventFilter(self)

        # مانیتور کردن خود patient_widget (برای switch tab)
        if self.patient_widget is not None:
            self.patient_widget.installEventFilter(self)

        # ✅ جدید: مانیتور کردن وضعیت کل برنامه با سیگنال
        self._app = QApplication.instance()
        if self._app is not None:
            self._app.applicationStateChanged.connect(self._on_app_state_changed)

        # وضعیت‌ها
        self._is_recording = False
        self._is_paused = False
        self._playback_mode = False

        self._stream: sd.InputStream | None = None
        self._audio_q: queue.Queue[np.ndarray] = queue.Queue()
        self._audio_frames: list[np.ndarray] = []

        self._sample_rate = 16000
        self._channels = 1
        self._dtype = "int16"

        self._file_path: Path | None = None

        # UI
        self._build_ui()

        # تایمر به‌روزرسانی UI و موج (حالت ضبط)
        self._tick_ms = 60
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._vu_level = 0.0
        self._elapsed_ms = 0  # زمان ضبط

        # پخش (playback)
        self._player_data: np.ndarray | None = None
        self._player_start_t: float | None = None
        self._player_duration_ms: int = 0
        self._player_offset_ms: int = 0  # نقطه شروع پخش (برای Seek)
        self._player_sr: int | None = None
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._on_play_tick)

        # پیش‌فرض پنهان
        self.setVisible(False)

    def _on_app_state_changed(self, state):
        """
        وقتی کل برنامه فوکوس را از دست می‌دهد (ApplicationInactive)،
        اگر پاپ‌آپ دیده می‌شود → آن را مخفی کن و وضعیت میکروفون را به‌روزرسانی کن.
        """
        try:
            if state == Qt.ApplicationInactive:
                if not self._inline_mode and self.isVisible():
                    self.hide()
                    try:
                        self.method_check_status_mic_btn(False)
                    except Exception:
                        pass
        except Exception:
            pass

    # 🔹 جلوگیری از بسته شدن با کلیک خارج
    def focusOutEvent(self, event):
        # کاملاً نادیده گرفتن focusOutEvent تا پنجره نپرد
        event.ignore()
        self.activateWindow()  # دوباره فعال کردن پنجره
        self.raise_()

    def mousePressEvent(self, event):
        # جلوگیری از انتشار کلیک به والدین
        event.accept()
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        """
        کنترل رفتار پاپ‌آپ در این حالت‌ها:
        - پنجره اصلی:
            * WindowDeactivate (Alt+Tab)
            * Hide (minimize)
            * Close (بسته شدن برنامه)
        - patient_widget:
            * Hide (معمولاً وقتی تب عوض می‌شود)
        """
        et = event.type()

        # 1) رویدادهای پنجره اصلی
        if obj is self._main_window:
            if et in (QEvent.WindowDeactivate, QEvent.Hide, QEvent.Close):
                if et == QEvent.Close:
                    # برنامه در حال بسته شدن است → همه چیز را تمیز کن و ببند
                    self._on_delete_clicked()
                else:
                    # 🔹 حتی در صورت Deactivate هم پنجره نباید بپرد
                    # فقط در صورت minimize یا hide کردن اصلی
                    if et == QEvent.Hide:
                        if not self._inline_mode and self.isVisible():
                            self.hide()
                            try:
                                self.method_check_status_mic_btn(False)
                            except Exception:
                                pass

        # 2) رویدادهای خود patient_widget (مثلاً وقتی تب عوض می‌شود)
        elif obj is self.patient_widget:
            if et == QEvent.Hide:
                # یعنی این تب مخفی شده (tab switch) → پاپ‌آپ را هم ببند
                if not self._inline_mode and self.isVisible():
                    self.hide()
                    try:
                        self.method_check_status_mic_btn(False)
                    except Exception:
                        pass

        return super().eventFilter(obj, event)

    def _format_playback_label(self, current_ms: int, total_ms: int) -> str:
        """
        برچسب زمان در حالت پخش:
        current / total  به صورت  mm:ss / mm:ss
        """
        if total_ms <= 0:
            total_ms = 0
        cur_txt = self._format_time(current_ms // 1000)
        total_txt = self._format_time(total_ms // 1000)
        return f"{cur_txt} / {total_txt}"

    def show_under(self, button: QWidget):
        """
        پاپ‌آپ را دقیقا زیر دکمه میکروفون نشان می‌دهد.
        """
        if self._inline_mode:
            return
        btn_pos = button.mapToGlobal(button.rect().bottomLeft())
        x = btn_pos.x()
        y = btn_pos.y() + 20  # کمی فاصله
        self.move(x, y)
        self.raise_()
        self.show()
        self.activateWindow()

    # ----------------- UI با کادر شیشه‌ای -----------------
    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(10, 10, 10, 10)
        main.setSpacing(8)

        self.setStyleSheet("""
        QWidget {
            background-color: rgba(17, 24, 39, 0.95);
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        """)

        # ردیف بالا: ثانیه‌شمار + موج (stream)
        top = QHBoxLayout()
        top.setSpacing(6)

        self.lbl_time = QLabel("00:00")
        f = QFont()
        f.setBold(True)
        self.lbl_time.setFont(f)
        self.lbl_time.setStyleSheet("color:#e5e7eb;")
        top.addWidget(self.lbl_time)
        top.addSpacing(8)

        # 🔊 موج سفید / نوار پیشرفت
        self.vu = _MiniVUMeter(self)
        self.vu.setFixedHeight(25)
        self.vu.scrubbed.connect(self._on_scrubbed)
        top.addWidget(self.vu, 1)

        main.addLayout(top)

        # کنترل‌ها: Play / Pause-Record / Save / Delete / Report / Sync
        controls = QHBoxLayout()
        controls.setSpacing(6)

        self.btn_play = QPushButton("Play")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.setStyleSheet(self._btn_style("#10b981"))
        self.btn_play.clicked.connect(self._on_play_clicked)

        self.btn_record_pause = QPushButton("Pause")
        self.btn_record_pause.setCursor(Qt.PointingHandCursor)
        self.btn_record_pause.setStyleSheet(self._btn_style("#3b82f6"))
        self.btn_record_pause.clicked.connect(self._on_record_pause_clicked)

        self.btn_save = QPushButton("Save")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(self._btn_style("#22c55e"))
        self.btn_save.clicked.connect(self._on_save_clicked)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setStyleSheet(self._btn_style("#ef4444"))
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        self.btn_report = QPushButton("Report")
        self.btn_report.setCursor(Qt.PointingHandCursor)
        self.btn_report.setStyleSheet(self._btn_style("#6366f1"))
        self.btn_report.clicked.connect(self._on_report_clicked)

        # 🔹 دکمه Sync جدید
        self.btn_sync = QPushButton("Sync")
        self.btn_sync.setCursor(Qt.PointingHandCursor)
        self.btn_sync.setStyleSheet(self._btn_style("#8b5cf6"))
        self.btn_sync.clicked.connect(self._on_sync_clicked)
        self.btn_sync.setToolTip("Save and sync with server")

        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_record_pause)
        controls.addWidget(self.btn_save)
        controls.addWidget(self.btn_delete)
        controls.addWidget(self.btn_report)
        controls.addWidget(self.btn_sync)  # اضافه کردن دکمه Sync

        main.addLayout(controls)

        self._update_record_pause_label()
        self._refresh_buttons()

    @staticmethod
    def _btn_style(color_hex: str) -> str:
        return f"""
        QPushButton {{
            background: rgba(31, 41, 55, 0.9);
            color: #e5e7eb;
            border: 1px solid {color_hex};
            border-radius: 6px;
            padding: 4px 8px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: {color_hex};
            color: #ffffff;
        }}
        """

    # ---------- Public API used by ToolbarManager ----------
    def set_inline_mode(self, enabled: bool):
        self._inline_mode = bool(enabled)

    def is_recording(self) -> bool:
        return self._is_recording

    def is_paused(self) -> bool:
        return self._is_paused

    def get_elapsed_ms(self) -> int:
        return int(self._elapsed_ms)

    def get_elapsed_label(self) -> str:
        return self._format_time(self._elapsed_ms // 1000)

    def check_microphone_available(self) -> bool:
        try:
            _ = sd.query_devices()
            default_sr = sd.query_devices(kind="input")
            return True if default_sr else False
        except Exception:
            return False

    def start_recording_inline(self, selected_widget) -> bool:
        self._inline_mode = True
        if self._is_recording:
            return False
        return self._start_new_recording(selected_widget, show_ui=False)

    def stop_and_save_inline(self):
        self._on_save_clicked(inline_override=True)

    def cancel_recording_inline(self):
        self._on_delete_clicked(inline_override=True)

    def toggle_pause_inline(self):
        if not self._is_recording:
            return
        self._set_paused(not self._is_paused)

    def toggle_recording(self, selected_widget):
        """
        همان اینترفیس قبلی:
        - اگر در حال ضبط هستیم → فقط pause/resume شود
        - اگر ضبط فعال نیست → شروع ضبط جدید
        """
        if self._is_recording:
            # وقتی از روی آیکون میکروفون کلیک می‌کنی و در حال ضبط هستی → pause/resume
            self._set_paused(not self._is_paused)
            return

        self._inline_mode = False
        self._start_new_recording(selected_widget, show_ui=True)

    def _start_new_recording(self, selected_widget, show_ui: bool) -> bool:
        # شروع ضبط جدید
        study_uid = self._resolve_study_uid(selected_widget)
        if not study_uid:
            QMessageBox.information(self, "No Study", "Study UID not found.")
            return False

        dest_dir = ATTACHMENT_PATH / study_uid
        dest_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._file_path = dest_dir / f"REC_{timestamp}.wav"

        # ریست وضعیت
        self._audio_q = queue.Queue()
        self._audio_frames = []
        self._elapsed_ms = 0
        self._vu_level = 0.0
        self._player_offset_ms = 0
        self.vu.clear()
        self.lbl_time.setText("00:00")

        # استریم ورودی
        self._is_recording = True
        self._is_paused = False
        self._playback_mode = False
        self._start_stream()

        self._timer.start(self._tick_ms)
        if show_ui and not self._inline_mode:
            self.setVisible(True)
        else:
            self.setVisible(False)
        self._update_record_pause_label()
        self._refresh_buttons()
        return True

    # ---------- استریم ورودی ----------
    def _start_stream(self):
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            channels=self._channels,
            samplerate=self._sample_rate,
            dtype=self._dtype,
            callback=self._callback_capture
        )
        self._stream.start()

    def _stop_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None

    # ---------- Internals ----------
    def _resolve_study_uid(self, selected_widget) -> str | None:
        """
        تلاش برای گرفتن study_uid از ویجت انتخاب‌شده یا patient_widget
        """
        # اول از selected_widget.image_viewer.metadata_fixed
        try:
            if hasattr(selected_widget, "image_viewer") and selected_widget.image_viewer:
                md = getattr(selected_widget.image_viewer, "metadata_fixed", None)
                if md and "study_uid" in md:
                    return md["study_uid"]
        except Exception:
            pass

        # fallback: خود patient_widget
        try:
            uid = getattr(self.patient_widget, "study_uid", None)
            return uid
        except Exception:
            return None

    def _callback_capture(self, indata, frames, time_info, status):
        if status:
            pass
        if not self._is_recording or self._is_paused:
            return

        # کپی فریم‌ها داخل صف
        self._audio_q.put(indata.copy())

    def _on_timer(self):
        # اگر pause باشیم، هیچ‌چیز آپدیت نشود (موج و زمان ثابت بماند)
        if self._is_paused or not self._is_recording:
            return

        # انتقال فریم‌ها از صف به بافر و محاسبه level
        while not self._audio_q.empty():
            block = self._audio_q.get_nowait()
            self._audio_frames.append(block)
            # محاسبه level (میانگین قدر مطلق * ضریب)
            level = float(np.clip(np.abs(block).mean() * 8.0, 0.0, 1.0))
            self._vu_level = level

        self._elapsed_ms += self._tick_ms

        # UI (حالت ضبط)
        self.vu.set_mode("record")
        self.vu.set_level(self._vu_level)
        self.lbl_time.setText(self._format_time(self._elapsed_ms // 1000))

    @staticmethod
    def _format_time(seconds: int) -> str:
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"

    def _set_paused(self, paused: bool):
        """
        منطق مشترک pause / resume:
        """
        if not self._inline_mode:
            self.method_check_status_mic_btn()

        if not self._is_recording:
            self._is_paused = False
            self._update_record_pause_label()
            return

        if paused == self._is_paused:
            return

        self._is_paused = paused
        if self._is_paused:
            # 1) استریم میکروفن را ببند
            self._stop_stream()
            # 2) تایمر موج/ثانیه‌شمار را متوقف کن
            self._timer.stop()
            # 3) صف بافر را خالی کن
            self._audio_q = queue.Queue()

        else:
            # ادامه ضبط: استریم جدید باز شود
            self._start_stream()
            # تایمر دوباره شروع شود
            self._timer.start(self._tick_ms)

        self._update_record_pause_label()
        self._refresh_buttons()

    def _update_record_pause_label(self):
        """
        متن دکمه Pause/Record را بر اساس وضعیت تنظیم می‌کند.
        """
        if not hasattr(self, "btn_record_pause"):
            return
        if not self._is_recording:
            # وقتی ضبطی در جریان نیست، دکمه عملاً غیر فعال است
            self.btn_record_pause.setText("Pause")
            self.btn_record_pause.setEnabled(False)
        else:
            if self._is_paused:
                self.btn_record_pause.setText("Record")
            else:
                self.btn_record_pause.setText("Pause")
            self.btn_record_pause.setEnabled(True)

    def _refresh_buttons(self):
        # آیا روی دیسک فایل داریم؟
        has_file = bool(self._file_path and self._file_path.exists())
        # آیا در حافظه تا الان فریم ضبط‌شده داریم؟
        has_data = bool(self._audio_frames)

        # 🔹 Play:
        self.btn_play.setEnabled(self._is_recording or has_file or has_data)

        # Pause/Record فقط وقتی ضبط در جریان است
        self._update_record_pause_label()

        # Save وقتی در حال ضبط هستیم یا دیتا/فایل داریم فعال باشد
        self.btn_save.setEnabled(self._is_recording or has_file or has_data)

        # Delete وقتی فایل یا جلسه ضبط داریم
        self.btn_delete.setEnabled(self._is_recording or has_file or has_data)

        # Report فعلاً همیشه فعال
        self.btn_report.setEnabled(True)
        
        # 🔹 Sync وقتی فایل یا داده داریم فعال باشد
        self.btn_sync.setEnabled(self._is_recording or has_file or has_data)

    # ---------- Controls ----------
    def _on_stop_internal(self):
        """
        توقف ضبط بدون تغییر UI بیشتر (برای استفاده داخل Save).
        """
        if not self._is_recording and not self._stream:
            return

        # توقف استریم
        self._stop_stream()
        self._timer.stop()

        # ذخیره WAV
        if self._audio_frames and self._file_path is not None:
            data = np.concatenate(self._audio_frames, axis=0)
            try:
                sf.write(str(self._file_path), data, self._sample_rate)
                self.method_update_audio_counter()
            except Exception as e:
                QMessageBox.warning(self, "Save Error", f"Cannot save audio file:\n{e}")
                self._file_path = None

        self._is_recording = False
        self._is_paused = False
        self._player_offset_ms = 0
        self._update_record_pause_label()
        self._refresh_buttons()

    def _on_stop_clicked(self):
        """
        Stop فقط ضبط را متوقف می‌کند، popup را نمی‌بندد.
        """
        self._on_stop_internal()

    def _on_delete_clicked(self, inline_override: bool | None = None):
        """
        اگر delete زده شد:
        - اگر در حال ضبط هستیم → ضبط و تایمر فقط متوقف شوند
        - اگر قبلاً چیزی ذخیره شده بود → فایل حذف شود
        - playback قطع شود
        - UI ریست شود
        - popup بسته شود
        """
        inline_mode = self._inline_mode if inline_override is None else inline_override

        # 1) اگر در حال ضبط یا pause هستیم → فقط استریم و تایمر را متوقف کن
        if self._is_recording or self._stream:
            self._stop_stream()
            self._timer.stop()
            self._is_recording = False
            self._is_paused = False

        # 2) اگر در حال پخش هستیم، قطع کن
        self._stop_playback()

        # 3) اگر فایل قبلاً روی دیسک ذخیره شده بود → آن هم پاک شود
        if self._file_path and self._file_path.exists():
            try:
                os.remove(self._file_path)
            except Exception:
                pass
        self._file_path = None

        # 4) ریست کامل UI و بافرها
        self._audio_frames = []
        self._audio_q = queue.Queue()
        self._vu_level = 0.0
        self._elapsed_ms = 0
        self._player_offset_ms = 0
        self.vu.clear()
        self.lbl_time.setText("00:00")

        self._update_record_pause_label()
        self._refresh_buttons()

        # 5) بعد از Delete پاپ‌آپ پنهان شود
        if not inline_mode:
            self.hide()
            self.method_check_status_mic_btn(False)

    def _on_save_clicked(self, inline_override: bool | None = None):
        """
        اگر save زده شد:
        - اگر هنوز در حال ضبط است → اول stop (و فایل ذخیره شود)
        - popup بسته شود
        """
        inline_mode = self._inline_mode if inline_override is None else inline_override
        if self._is_recording or self._stream:
            self._on_stop_internal()

        # اگر هیچ چیز ضبط نشده بود، فقط پنهان می‌شود
        if not inline_mode:
            self.hide()
            self.method_check_status_mic_btn(False)

    # 🔹 متد جدید برای دکمه Sync
    def _on_sync_clicked(self):
        """
        Save + Sync: ذخیره فایل و سپس sync با سرور
        """
        if self._inline_mode:
            return
        # 1) ذخیره فایل (اگر در حال ضبط هستیم)
        if self._is_recording or self._stream:
            self._on_stop_internal()
        
        # 2) بررسی وجود فایل
        if not self._file_path or not self._file_path.exists():
            QMessageBox.warning(self, "No File", "No audio file to sync.")
            return
        
        # 3) بستن پاپ‌آپ
        self.hide()
        self.method_check_status_mic_btn(False)
        
        # 4) فراخوانی متد sync (اگر موجود باشد)
        if self.method_sync is not None:
            # استفاده از QTimer برای اطمینان از بسته شدن کامل پاپ‌آپ قبل از sync
            QTimer.singleShot(100, self.method_sync)
        else:
            print("Sync method not available")

    def _on_record_pause_clicked(self):
        """
        دکمه Pause/Record:
        """
        if not self._is_recording:
            return
        self._set_paused(not self._is_paused)

    def _build_play_data_from_memory(self):
        """
        در صورت امکان، داده صوتی را از حافظه (فریم‌ها) می‌سازد.
        """
        if not self._audio_frames:
            return None, None
        try:
            data = np.concatenate(self._audio_frames, axis=0)
        except ValueError:
            return None, None
        return data, self._sample_rate

    def _build_play_data_from_file(self):
        """
        در صورت امکان، داده صوتی را از روی فایل می‌خواند.
        """
        if not self._file_path or not self._file_path.exists():
            return None, None
        try:
            data, sr = sf.read(str(self._file_path), dtype="float32")
        except Exception:
            return None, None
        return data, sr

    def _start_playback(self, data: np.ndarray, sr: int, start_offset_ms: int = 0):
        """
        شروع پخش از داده داده‌شده، از offset مشخص (میلی‌ثانیه).
        """
        if data is None or len(data) == 0:
            return

        self._player_data = data
        self._player_sr = sr
        self._player_duration_ms = int(len(data) / sr * 1000) or 1

        # تصحیح offset
        start_offset_ms = max(0, min(start_offset_ms, self._player_duration_ms))
        self._player_offset_ms = start_offset_ms

        # محاسبه sample شروع
        start_sample = int((self._player_offset_ms / self._player_duration_ms) * len(data))

        try:
            sd.stop()
        except Exception:
            pass

        try:
            sd.play(data[start_sample:], sr)
        except Exception as e:
            QMessageBox.warning(self, "Play Error", f"Cannot play audio:\n{e}")
            self._stop_playback()
            return

        self._player_start_t = time.monotonic()
        self._playback_mode = True
        self._play_timer.start(60)

        # UI پخش
        self.vu.set_mode("playback")
        progress = self._player_offset_ms / self._player_duration_ms
        self.vu.set_playback_progress(progress)

        self.lbl_time.setText(
            self._format_playback_label(self._player_offset_ms, self._player_duration_ms)
        )

    def _on_play_clicked(self):
        """
        رفتار Play:
        """
        # اگر همین الان در حال پخش هستیم → toggle به stop
        if self._playback_mode:
            self._stop_playback()
            return

        data = None
        sr = None

        # اگر هنوز در session ضبط هستیم (recording/pause) و دیتا داریم → از حافظه
        if (self._is_recording or self._is_paused) and self._audio_frames:
            # اگر هنوز در حال ضبط فعال هستیم، قبل از پخش آن را pause کن
            if self._is_recording and not self._is_paused:
                self._set_paused(True)
            data, sr = self._build_play_data_from_memory()

        # اگر داده از حافظه نداریم، از روی فایل (بعد از Save/Stop)
        if data is None or sr is None:
            data, sr = self._build_play_data_from_file()

        if data is None or sr is None:
            return

        # شروع پخش از offset فعلی
        self._start_playback(data, sr, self._player_offset_ms)

    def _stop_playback(self):
        try:
            sd.stop()
        except Exception:
            pass
        self._playback_mode = False
        self._player_data = None
        self._player_start_t = None
        self._player_duration_ms = 0
        self._player_sr = None
        self._play_timer.stop()
        self._player_offset_ms = 0

    def _on_play_tick(self):
        if not self._playback_mode or self._player_start_t is None or self._player_duration_ms <= 0:
            return
        elapsed_since_start = int((time.monotonic() - self._player_start_t) * 1000)
        total_elapsed = self._player_offset_ms + elapsed_since_start

        if total_elapsed >= self._player_duration_ms:
            total_elapsed = self._player_duration_ms

        progress = total_elapsed / self._player_duration_ms
        self.vu.set_mode("playback")
        self.vu.set_playback_progress(progress)
        self.lbl_time.setText(self._format_playback_label(total_elapsed, self._player_duration_ms))

        if total_elapsed >= self._player_duration_ms:
            self._stop_playback()

    def _on_scrubbed(self, progress: float):
        """
        واکنش به Seek روی waveform با موس.
        """
        try:
            p = float(progress)
        except Exception:
            return
        p = max(0.0, min(1.0, p))

        # اگر داده پخش نداریم، سعی می‌کنیم بسازیم
        data, sr = None, None
        if self._audio_frames:
            data, sr = self._build_play_data_from_memory()
        if (data is None or sr is None) and self._file_path and self._file_path.exists():
            data, sr = self._build_play_data_from_file()

        if data is None or sr is None or len(data) == 0:
            return

        self._player_data = data
        self._player_sr = sr
        self._player_duration_ms = int(len(data) / sr * 1000) or 1

        new_offset_ms = int(p * self._player_duration_ms)
        self._player_offset_ms = new_offset_ms

        self.vu.set_mode("playback")
        self.vu.set_playback_progress(p)

        self.lbl_time.setText(
            self._format_playback_label(new_offset_ms, self._player_duration_ms)
        )

        if self._playback_mode:
            self._start_playback(data, sr, self._player_offset_ms)
        else:
            self._player_start_t = None

    def _on_report_clicked(self):
        print('report')
        self._on_save_clicked()  # save audio
        asyncio.create_task(self.patient_widget.open_report_in_echo_mind(self._file_path))

    # async def open_report_in_echo_mid(self):
    #     echo_mind_window = self.patient_widget.ai_chat_layout_ui()  # open ECHO MIND window
    #
    #     await asyncio.sleep(0.1)
    #     echo_mind_window._open_mode_page('report')  # open report page
    #
    #     # print('path audio:', self._file_path)
    #     echo_mind_window._page.composer._choose_file(self._file_path)  # send audio to report page


# ----------------- موج / نوار پیشرفت شبیه ChatGPT -----------------
class _MiniVUMeter(QWidget):
    """
    دو حالت:
    - record: نمایش موج صدا (bar های سفید)
        * موج از چپ شروع می‌شود و به سمت راست پیش می‌رود.
        * ابتدا نوار خالی است، با هر نمونه، ستون جدیدی از سمت چپ اضافه می‌شود
          تا زمانی که به حداکثر bar_count برسد.
    - playback: همان موج ثابت، ولی:
        * ستون‌های "پخش‌شده" روشن‌تر
        * ستون‌های "باقی‌مانده" کم‌رنگ‌تر
        * یک خط playhead روی طول همین موج حرکت می‌کند
    همچنین با کلیک/درگ روی آن می‌توان Seek کرد.
    """

    scrubbed = Signal(float)  # مقدار progress بین 0 و 1

    def __init__(self, parent=None, bar_count: int = 64):
        super().__init__(parent)
        self._bar_count = bar_count
        # حالا به جای پر کردن با صفر، از لیست خالی شروع می‌کنیم
        self._levels: list[float] = []
        self._mode: str = "record"      # "record" or "playback"
        self._progress: float = 0.0     # برای playback
        self._is_dragging: bool = False

        self.setMinimumHeight(28)
        self.setCursor(Qt.PointingHandCursor)

    # --- API برای حالت ضبط ---
    def set_mode(self, mode: str):
        if mode not in ("record", "playback"):
            return
        if self._mode != mode:
            self._mode = mode
            self.update()

    def set_level(self, level: float):
        """
        برای حالت ضبط (record): موج را به‌روز می‌کند.
        موج از چپ شروع می‌شود و به سمت راست رشد می‌کند.
        """
        if self._mode != "record":
            return
        if level is None:
            level = 0.0
        try:
            v = float(level)
        except Exception:
            v = 0.0
        v = max(0.0, min(1.0, v))

        # اگر هنوز به حداکثر نرسیدیم → فقط append (از چپ به راست پر می‌شود)
        if len(self._levels) < self._bar_count:
            self._levels.append(v)
        else:
            # وقتی پر شد → قدیمی‌ترین (چپ) حذف شود، جدید به انتها اضافه شود
            self._levels.pop(0)
            self._levels.append(v)

        self.update()

    def clear(self):
        self._levels = []
        self._progress = 0.0
        self.update()

    # --- API برای حالت پخش ---
    def set_playback_progress(self, progress: float):
        self._mode = "playback"
        try:
            p = float(progress)
        except Exception:
            p = 0.0
        self._progress = max(0.0, min(1.0, p))
        self.update()

    # --- Mouse (Seek) ---
    def _pos_to_progress(self, x: int) -> float:
        r: QRect = self.rect()
        if r.width() <= 0:
            return 0.0
        rel = (x - r.left()) / r.width()
        return max(0.0, min(1.0, rel))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            p = self._pos_to_progress(event.pos().x())
            self.set_playback_progress(p)
            self.scrubbed.emit(p)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            p = self._pos_to_progress(event.pos().x())
            self.set_playback_progress(p)
            self.scrubbed.emit(p)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._is_dragging:
            self._is_dragging = False
            p = self._pos_to_progress(event.pos().x())
            self.set_playback_progress(p)
            self.scrubbed.emit(p)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # --- رسم ---
    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        r: QRect = self.rect()
        if r.width() <= 0 or r.height() <= 0:
            return

        mid_y = r.center().y()
        half_h = (r.height() / 2.0) - 2.0

        # خط وسط (برای هر دو حالت)
        base_pen = QPen(QColor(255, 255, 255, 80), 1)
        painter.setPen(base_pen)
        painter.drawLine(r.left(), mid_y, r.right(), mid_y)

        n = len(self._levels)
        if n == 0:
            return

        # برای اینکه در نهایت وقتی موج کامل شد، دقیقاً عرض را پر کند:
        step = r.width() / max(1, self._bar_count)

        # در playback، تعداد ستون‌های موثر برای progress، همان n است
        progress_idx = int(self._progress * n) if self._mode == "playback" else -1

        for i in range(n):
            lvl = self._levels[i]
            if lvl <= 0.01:
                continue

            x = int(r.left() + (i + 0.5) * step)
            hh = half_h * lvl
            y1 = int(mid_y - hh)
            y2 = int(mid_y + hh)

            # رنگ هر ستون براساس اینکه «پخش‌شده» است یا نه
            if self._mode == "playback":
                if i < progress_idx:
                    color = QColor(255, 255, 255, 230)   # ستون‌های پخش‌شده: روشن
                else:
                    color = QColor(255, 255, 255, 90)    # هنوز پخش‌نشده: کم‌رنگ
            else:
                color = QColor(255, 255, 255, 220)       # حالت record: همه مثل هم

            bar_pen = QPen(color)
            bar_pen.setWidth(2)
            painter.setPen(bar_pen)
            painter.drawLine(x, y1, x, y2)

        # در حالت playback یک playhead هم روی همین موج بکش
        if self._mode == "playback":
            progress_x = r.left() + int(self._progress * r.width())
            head_pen = QPen(QColor(255, 255, 255, 230), 2)
            painter.setPen(head_pen)
            painter.drawLine(progress_x, r.top() + 2, progress_x, r.bottom() - 2)
