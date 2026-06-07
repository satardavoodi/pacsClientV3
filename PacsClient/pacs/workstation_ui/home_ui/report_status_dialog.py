# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                QComboBox, QPushButton, QTextEdit, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer
import qtawesome as qta
from modules.network.socket_report_status_service import REPORT_STATUSES, STATUS_COLORS


# Import from service (will be defined there)


class ReportStatusDialog(QDialog):
    """
    Dialog for changing report status of a study
    """
    
    statusChanged = Signal(str, str, str)  # study_uid, old_status, new_status
    
    def __init__(self, parent=None, study_uid: str = "", current_status: str = "pending", 
                 patient_name: str = "", patient_id: str = "", reporting_physician: str = ""):
        super().__init__(parent)
        self.study_uid = study_uid
        self.current_status = current_status
        self.patient_name = patient_name
        self.patient_id = patient_id
        self.reporting_physician = reporting_physician
        self._comment = ""  # Initialize comment
        self._initial_comment = ""
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        self.setWindowTitle("Change Report Status")
        self.setMinimumWidth(640)
        self.setMinimumHeight(300)
        
        # Dialog styling - dark theme
        self.setStyleSheet("""
            QDialog {
                background: #0f1419;
            }
            QLabel {
                color: #e2e8f0;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Patient info
        info_label = QLabel(f"Patient: {self.patient_name} ({self.patient_id})")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #e2e8f0;")
        layout.addWidget(info_label)

        physician_text = str(self.reporting_physician or "").strip() or "N/A"
        self.physician_label = QLabel(f"Reporting Physician: {physician_text}")
        self.physician_label.setWordWrap(True)
        self.physician_label.setStyleSheet("font-size: 13px; color: #cbd5e1; line-height: 1.4;")
        layout.addWidget(self.physician_label)
        
        study_label = QLabel(f"Study UID: {self.study_uid[:50]}...")
        study_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(study_label)
        
        # Current status
        current_status_label = QLabel(f"Current Status: {REPORT_STATUSES.get(self.current_status, self.current_status)}")
        current_status_label.setStyleSheet(f"font-size: 13px; color: {STATUS_COLORS.get(self.current_status, '#f59e0b')};")
        layout.addWidget(current_status_label)
        
        # Status selection
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("New Status:"))
        
        self.status_combo = QComboBox()
        self.status_combo.setStyleSheet("""
            QComboBox {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                color: #e2e8f0;
                font-size: 14px;
            }
            QComboBox:hover {
                border: 1px solid #3182ce;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #1a202c;
                border: 1px solid #4a5568;
                selection-background-color: #3182ce;
                color: #e2e8f0;
            }
        """)
        
        # Add statuses to combo box
        for status_key, status_label in REPORT_STATUSES.items():
            self.status_combo.addItem(status_label, status_key)
            # Set current status as selected
            if status_key == self.current_status:
                self.status_combo.setCurrentIndex(self.status_combo.count() - 1)
        
        status_layout.addWidget(self.status_combo)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Comment field
        comment_label = QLabel("Comment (Optional):")
        comment_label.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        layout.addWidget(comment_label)
        
        self.comment_text = QTextEdit()
        self.comment_text.setPlaceholderText("Comment about status change...")
        self.comment_text.setMaximumHeight(100)
        self.comment_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                color: #e2e8f0;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #3182ce;
            }
        """)
        layout.addWidget(self.comment_text)

        # ── Local Physician Reminder (2026-06-06) ────────────────────────
        # Strictly local: stored only on this workstation
        # (PacsClient.utils.local_reminders → user_data JSON). Never sent to
        # the PACS / reception / reporting server and independent of the
        # server-synced status/comment above.
        self._build_local_reminder_section(layout)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #4a5568;
                color: #e2e8f0;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-size: 14px;
                min-width: 120px;
            }
            QPushButton:hover {
                background: #2d3748;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("Apply Change")
        apply_btn.setMinimumWidth(140)
        apply_btn.setIcon(qta.icon('fa5s.check', color='#10b981'))
        apply_btn.setStyleSheet("""
            QPushButton {
                background: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-size: 14px;
                min-width: 140px;
            }
            QPushButton:hover {
                background: #2c5aa0;
            }
        """)
        apply_btn.clicked.connect(self.apply_change)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    # ── Local Physician Reminder (local-only, no server I/O) ────────────
    # After exec() the caller checks `_local_reminder_saved` to refresh the
    # row's pin/alarm/note indicators.

    def _build_local_reminder_section(self, layout):
        from PySide6.QtWidgets import QFrame, QToolButton

        try:
            from PacsClient.utils.local_reminders import get_reminder
            reminder = get_reminder(self.patient_id)
        except Exception:
            reminder = {"pinned": False, "alarm": False, "note": ""}
        self._initial_reminder = dict(reminder)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { background: #2d3748; border: none; min-height: 1px; max-height: 1px; }")
        layout.addWidget(sep)

        header = QLabel("Local Physician Reminder")
        header.setStyleSheet("font-size: 13px; font-weight: 700; color: #93c5fd;")
        layout.addWidget(header)
        subtitle = QLabel("Stored only on this workstation — never sent to the server.")
        subtitle.setStyleSheet("font-size: 11px; color: #64748b;")
        layout.addWidget(subtitle)

        toggles = QHBoxLayout()
        toggles.setSpacing(8)

        def _toggle_btn(text, icon_name, icon_color, tooltip, checked):
            btn = QToolButton()
            btn.setText(" " + text)
            try:
                btn.setIcon(qta.icon(icon_name, color=icon_color))
            except Exception:
                pass
            btn.setCheckable(True)
            btn.setChecked(bool(checked))
            btn.setToolTip(tooltip)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QToolButton {
                    background: #1a202c; color: #cbd5e1;
                    border: 1px solid #4a5568; border-radius: 4px;
                    padding: 6px 12px; font-size: 12px;
                }
                QToolButton:hover { border-color: #3182ce; }
                QToolButton:checked {
                    background: #1e3a5f; color: #ffffff; border-color: #3b82f6;
                }
            """)
            toggles.addWidget(btn)
            return btn

        self.pin_toggle = _toggle_btn(
            "Pin", 'fa5s.thumbtack', '#3b82f6',
            "Pin this patient — appears at the TOP of future search results (local only)",
            reminder.get("pinned"),
        )
        self.alarm_toggle = _toggle_btn(
            "Alarm", 'fa5s.exclamation-triangle', '#ef4444',
            "Mark as important / needs attention — red warning shown in the patient list (local only)",
            reminder.get("alarm"),
        )
        toggles.addStretch()
        layout.addLayout(toggles)

        self.local_note_text = QTextEdit()
        self.local_note_text.setPlaceholderText(
            "Private note for this patient (visible only on this workstation)..."
        )
        self.local_note_text.setMaximumHeight(70)
        self.local_note_text.setPlainText(str(reminder.get("note") or ""))
        self.local_note_text.setStyleSheet("""
            QTextEdit {
                background: #131a24; border: 1px dashed #3b5371;
                border-radius: 4px; padding: 8px;
                color: #bfdbfe; font-size: 12px;
            }
            QTextEdit:focus { border: 1px solid #3b82f6; }
        """)
        layout.addWidget(self.local_note_text)

    def _save_local_reminder_if_changed(self):
        """Persist the local section (file only — never the server).

        Called on BOTH Apply and Cancel/close: the local reminder is
        independent of the server-synced status change above it.
        """
        if not hasattr(self, 'pin_toggle'):
            return
        try:
            current = {
                "pinned": bool(self.pin_toggle.isChecked()),
                "alarm": bool(self.alarm_toggle.isChecked()),
                "note": self.local_note_text.toPlainText().strip(),
            }
            initial = getattr(self, '_initial_reminder', {}) or {}
            if (current["pinned"] == bool(initial.get("pinned"))
                    and current["alarm"] == bool(initial.get("alarm"))
                    and current["note"] == str(initial.get("note") or "").strip()):
                return  # nothing changed
            from PacsClient.utils.local_reminders import set_reminder
            set_reminder(
                self.patient_id,
                pinned=current["pinned"],
                alarm=current["alarm"],
                note=current["note"],
                study_uid=self.study_uid,
            )
            self._local_reminder_saved = True
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "local reminder save failed", exc_info=True
            )

    def done(self, result):  # noqa: D401 — Qt override
        """Save the local-only section on ANY dialog close (Apply or Cancel)."""
        self._save_local_reminder_if_changed()
        super().done(result)

    def apply_change(self):
        """Apply the status change"""
        new_status = self.status_combo.currentData()
        comment = self.comment_text.toPlainText().strip()

        status_changed = new_status != self.current_status
        comment_changed = comment != (self._initial_comment or "")

        if not status_changed and not comment_changed:
            QMessageBox.information(self, "Information", "No changes to apply.")
            return

        # Store comment for retrieval
        self._comment = comment
        if not status_changed:
            # Reuse the same status so caller can still submit comment-only changes.
            new_status = self.current_status

        # Accept dialog first, then emit signal
        self.accept()

        # Emit signal after dialog is closed to avoid blocking
        QTimer.singleShot(0, lambda: self.statusChanged.emit(self.study_uid, self.current_status, new_status))

    def set_comment(self, comment: str) -> None:
        """Prefill comment editor with existing server-side comment."""
        value = str(comment or "")
        self._initial_comment = value
        self.comment_text.setPlainText(value)

    def set_reporting_physician(self, reporting_physician: str) -> None:
        """Update reporting physician label when fetched asynchronously."""
        self.reporting_physician = str(reporting_physician or "")
        physician_text = self.reporting_physician.strip() or "N/A"
        if hasattr(self, 'physician_label'):
            self.physician_label.setText(f"Reporting Physician: {physician_text}")
    
    def get_new_status(self) -> str:
        """Get the selected new status"""
        return self.status_combo.currentData()
    
    def get_comment(self) -> str:
        """Get the comment text"""
        return self.comment_text.toPlainText().strip()

