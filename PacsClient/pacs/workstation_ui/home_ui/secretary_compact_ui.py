"""Voice-first presentation; command routing remains in the existing controller."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy, QComboBox


def configure_compact_secretary(widget):
    widget._compact_companion = True
    widget.orb_button._compact_avatar = True
    widget.setMinimumHeight(188)
    widget.setMaximumHeight(16777215)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout = widget.layout()
    # Empty legacy rows otherwise consume spacing even with hidden children.
    while layout.count():
        item = layout.takeAt(0)
        if item.layout() is not None:
            item.layout().deleteLater()
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(6)
    row = QHBoxLayout()
    row.setSpacing(8)
    widget.orb_button.setFixedSize(128, 128)
    widget.orb_button.setAccessibleName('Record Secretary command')
    widget.orb_button.setToolTip('Click to record; click again to finish')
    row.addWidget(widget.orb_button)
    widget.log_box.setFixedHeight(24)
    widget.log_box.setStyleSheet("QPlainTextEdit {background:transparent;border:none;color:#cce9ff;font:16px 'Segoe UI';}")
    text_column = QVBoxLayout()
    text_column.setSpacing(8)
    status_row = QHBoxLayout()
    widget._status_icon = QLabel(widget)
    widget._status_icon.setFixedSize(20, 24)
    status_row.addWidget(widget._status_icon)
    status_row.addWidget(widget.log_box, 1)
    text_column.addLayout(status_row)
    row.addLayout(text_column, 1)
    row.setAlignment(Qt.AlignVCenter)
    layout.insertLayout(0, row)
    widget.command_input.hide()
    widget.command_send.hide()
    widget.report_issue_button.hide()
    widget.memory_label.show()
    widget.memory_new_btn.show()
    widget.log_expand_icon.hide()
    hint = QLabel('Click the circle to speak', widget)
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#a9bfd4;font:13px 'Segoe UI';background:transparent;")
    widget._status_hint = hint
    text_column.addWidget(hint)
    actions = QHBoxLayout()
    actions.setSpacing(8)
    open_button = QPushButton('Conversation', widget)
    open_button.setToolTip('Open conversation')
    open_button.clicked.connect(lambda: open_conversation(widget))
    actions.addWidget(open_button, 1)
    mute = QPushButton('Sound on', widget)
    mute.setCheckable(True)
    mute.setToolTip('Mute spoken replies; recording remains available')
    mute.toggled.connect(lambda checked: mute_replies(widget, mute, checked))
    actions.addWidget(mute, 1)
    for button in (open_button, mute):
        button.setFixedHeight(30)
        button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        button.setStyleSheet("QPushButton {font:13px 'Segoe UI';color:#d9eaf6;background:#1b3043;border:1px solid #3b596f;border-radius:7px;padding:0 8px;} QPushButton:hover {background:#25445e;} QPushButton:checked {background:#293443;}")
    layout.addLayout(actions)
    widget.mode_selector = QComboBox(widget)
    for label, value in (("Act", "act"), ("Ask", "ask"), ("Guide", "guide"), ("Help Ticket", "help_ticket")):
        widget.mode_selector.addItem(label, value)
    widget.mode_selector.setAccessibleName("Secretary mode")
    widget.mode_selector.setToolTip("Selected mode applies to every voice and text request")
    widget.mode_selector.setFixedHeight(30)
    widget.mode_selector.setMinimumWidth(72)
    widget.mode_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    widget.mode_selector.setMinimumWidth(112)
    widget.mode_selector.setStyleSheet("QComboBox {font:13px 'Segoe UI';color:#d9eaf6;background:#1b3043;border:1px solid #3b596f;border-radius:7px;padding:0 8px;} QComboBox:hover {background:#25445e;} QComboBox::drop-down {border:none;width:18px;} QComboBox QAbstractItemView {color:#d9eaf6;background:#1b3043;selection-background-color:#25445e;}")
    text_column.insertWidget(0, widget.mode_selector)
    text_column.setAlignment(Qt.AlignVCenter)
    def mode_changed(_):
        if widget._secretary_busy or widget._rec_running:
            return
        widget._set_thinking_status("Ready")
    widget.mode_selector.currentIndexChanged.connect(mode_changed)
    memory_row = QHBoxLayout()
    widget.memory_label.setText("Memory #1 - Cycle 0/10")
    widget.memory_label.setStyleSheet("color:#a9bfd4;font:12px 'Segoe UI';background:transparent;")
    widget.memory_new_btn.setFixedHeight(26)
    widget.memory_new_btn.setFixedWidth(54)
    widget.memory_new_btn.setStyleSheet("QPushButton {font:12px 'Segoe UI';color:#a9bfd4;background:transparent;border:1px solid #3b596f;border-radius:6px;padding:0 6px;} QPushButton:hover {background:#1b3043;color:#d9eaf6;}")
    widget.memory_new_btn.setToolTip("Start a new conversation; previous memory stays saved")
    memory_row.addWidget(widget.memory_label, 1)
    memory_row.addWidget(widget.memory_new_btn)
    layout.addLayout(memory_row)
    widget._reply_muted = False


def open_conversation(widget):
    if widget._response_panel is None:
        from .secretary_response_panel import SecretaryResponsePanel
        widget._response_panel = SecretaryResponsePanel(widget.window())
        widget._response_panel.detailsRequested.connect(widget._toggle_log_popup)
        widget._response_panel.commandSubmitted.connect(widget.submit_text_command)
    widget._response_panel.set_muted(widget._reply_muted)
    widget._response_panel.open_response(expanded=True)


def mute_replies(widget, button, checked):
    widget._reply_muted = checked
    button.setText('Sound off' if checked else 'Sound on')
    if widget._response_panel is not None:
        widget._response_panel.set_muted(checked)


def paint_compact_orb(orb, painter):
    """Use the original orb renderer, including its existing pulse ring."""
    if orb._active and orb._active_frames:
        frame = orb._active_frames[orb._frame_index]
    elif orb._error_mode and orb._error_frames:
        frame = orb._error_frames[orb._error_frame_index % len(orb._error_frames)]
    else:
        frame = orb._inactive_frame
    if frame is not None and not frame.isNull():
        painter.drawPixmap(orb.rect(), frame)


def update_companion_status(widget, stage):
    import qtawesome as qta
    value = stage.lower()
    color, icon, title, hint = "#a9bfd4", "fa5s.circle", "Ready", "Click the circle to speak"
    if "done" in value:
        color, icon, title, hint = "#55d6a0", "fa5s.check-circle", "Done", "Completed. Click to give another command"
    elif "failed" in value or "error" in value:
        color, icon, title, hint = "#f28b82", "fa5s.exclamation-circle", "Could not complete", "Open conversation for details; click to retry"
    elif "awaiting answer" in value:
        color, icon, title, hint = "#f0c674", "fa5s.question-circle", "Your answer needed", "Answer the question to continue"
    elif "cancelled" in value:
        color, icon, title, hint = "#a9bfd4", "fa5s.circle", "Cancelled", "Click the circle to give another command"
    elif "confirm" in value:
        color, icon, title, hint = "#f0c674", "fa5s.question-circle", "Your approval needed", "Review the confirmation to continue"
    elif "listening" in value:
        color, icon, title, hint = "#8ee3f1", "fa5s.microphone", "Listening", "Click again to finish recording"
    elif "transcrib" in value:
        color, icon, title, hint = "#8ee3f1", "fa5s.file-audio", "Transcribing", "Converting your voice to text"
    elif value != "ready":
        color, icon, title, hint = "#f0c674", "fa5s.cog", "Working", "Understanding your command"
        if "execut" in value:
            hint = "Applying your command"
        elif "repair" in value:
            hint = "Checking and correcting the action"
    widget._set_log_box_text(title)
    widget.log_box.setStyleSheet(f"QPlainTextEdit {{background:transparent;border:none;color:{color};font:16px 'Segoe UI';}}")
    widget._status_icon.setPixmap(qta.icon(icon, color=color).pixmap(18, 18))
    widget._status_hint.setText(hint)
    widget.log_box.setAccessibleDescription(hint)
