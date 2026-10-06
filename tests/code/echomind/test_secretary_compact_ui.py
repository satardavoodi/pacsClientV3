"""Compact companion uses the existing recording control and a full text composer."""
from PySide6.QtWidgets import QApplication
from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel


def test_home_companion_size_and_idle_render():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    widget.resize(280, 150)
    widget.show()
    app.processEvents()
    assert 76 <= widget.orb_button.width() <= 180
    assert widget.height() >= 188
    assert widget.layout().count() == 3
    assert widget.command_input.isHidden()
    assert widget.command_send.isHidden()
    assert widget.log_box.toPlainText() == 'Ready'
    assert not widget.grab().isNull()
    widget.cleanup()
    widget.close()


def test_conversation_composer_and_mute_without_speech():
    app = QApplication.instance() or QApplication([])
    panel = SecretaryResponsePanel(speech_factory=lambda _: None)
    commands = []
    panel.commandSubmitted.connect(commands.append)
    panel.command_input.setText('Sort studies by image count')
    panel._submit_command()
    assert commands == ['Sort studies by image count']
    panel.set_muted(True)
    assert panel._muted
    panel.close()


def test_compact_orb_reuses_original_renderer():
    from PySide6.QtGui import QPixmap, QPainter
    from PacsClient.pacs.workstation_ui.home_ui.secretary_compact_ui import paint_compact_orb
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    orb = widget.orb_button
    original = orb._render_frame(128, active=True, phase=.2, error=False)
    orb._active_frames = [original]
    orb._frame_index = 0
    orb._active = True  # Paint only; do not start recording.
    actual = QPixmap(128, 128)
    actual.fill()
    painter = QPainter(actual)
    paint_compact_orb(orb, painter)
    painter.end()
    expected = QPixmap(128, 128)
    expected.fill()
    painter = QPainter(expected)
    painter.drawPixmap(orb.rect(), original)
    painter.end()
    assert actual.toImage() == expected.toImage()
    orb._active = False
    widget.cleanup()
    widget.close()


def test_listening_panel_keeps_soft_glow_without_sidebar_wave_lines():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    widget.resize(294, 200)
    calls = []
    widget._draw_sidebar_waves = lambda *args: calls.append(True)
    widget._ui_state = 'listening'
    widget._fade_t = 1.0
    widget.show()
    app.processEvents()
    assert not widget.grab().isNull()
    assert not calls
    widget.cleanup()
    widget.close()


def test_companion_resizes_orb_and_restores_new_memory_control():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    widget.resize(310, 188)
    widget.show()
    app.processEvents()
    small = widget.orb_button.width()
    widget.resize(310, 380)
    app.processEvents()
    assert widget.orb_button.width() > small
    assert widget.memory_new_btn.isVisible()
    class Memory:
        def new_memory(self): self.created = True
        def get_current_info(self): return (2, 0)
    memory = Memory()
    from types import SimpleNamespace
    widget._secretary_orchestrator = SimpleNamespace(memory_store=memory)
    widget._ensure_secretary_runtime = lambda: True
    widget.memory_new_btn.click()
    assert memory.created
    assert widget.memory_label.text() == "Memory #2 - Cycle 0/10"
    widget._secretary_orchestrator = None
    widget.cleanup()
    widget.close()


def test_companion_progress_and_completion_are_distinct():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    for stage, title, detail in [
        ("Listening", "Listening", "finish recording"),
        ("Phase 1: Transcribing", "Transcribing", "voice to text"),
        ("Phase 2: Module Routing", "Working", "Understanding"),
        ("Executing", "Working", "Applying"),
        ("Done", "Done", "Completed"),
        ("Failed", "Could not complete", "retry"),
    ]:
        widget._set_thinking_status(stage)
        assert widget.log_box.toPlainText() == title
        assert detail in widget._status_hint.text()
        assert not widget._status_icon.pixmap().isNull()
    widget._set_thinking_status("Done")
    assert "#55d6a0" in widget.log_box.styleSheet()
    widget._set_thinking_status("Listening")
    assert "#55d6a0" not in widget.log_box.styleSheet()
    widget.cleanup()
    widget.close()


def test_compact_modes_fit_short_sidebar_without_extra_row():
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    widget.resize(294, 188)
    widget.show()
    app.processEvents()
    assert widget.height() == 188
    assert widget.layout().count() == 3
    assert widget.mode_selector.isVisible()
    for control in (widget.mode_selector, widget.memory_new_btn, widget.memory_label, widget.orb_button):
        rect = control.rect()
        top = control.mapTo(widget, rect.topLeft())
        bottom = control.mapTo(widget, rect.bottomRight())
        assert top.y() >= 0 and bottom.y() < widget.height()
        assert top.x() >= 0 and bottom.x() < widget.width()
    widget.cleanup()
    widget.close()


def test_compact_action_buttons_have_equal_geometry_and_mode_is_with_status():
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtCore import QPoint
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    widget.resize(294, 210)
    widget.show()
    app.processEvents()
    sound = next(b for b in widget.findChildren(QPushButton) if b.text() == "Sound on")
    mode = widget.mode_selector
    conversation = next(b for b in widget.findChildren(QPushButton) if b.text() == "Conversation")
    assert abs(conversation.width() - sound.width()) <= 1
    assert conversation.mapTo(widget, QPoint()).y() == sound.mapTo(widget, QPoint()).y()
    assert mode.mapTo(widget, QPoint(0, mode.height())).y() < widget.log_box.mapTo(widget, QPoint()).y()
    widget.cleanup()
    widget.close()


def test_help_ticket_routes_transcript_to_existing_issue_flow(monkeypatch):
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.home_ui import support_issue_dialog
    from PacsClient.pacs.workstation_ui.home_ui.home_panel import widget as home_module
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    home = SimpleNamespace()
    opened = []
    monkeypatch.setattr(home_module, "get_home_widget", lambda: home)
    monkeypatch.setattr(support_issue_dialog, "open_support_issue_form", lambda h, text: opened.append((h, text)))
    monkeypatch.setattr(widget, "_ensure_secretary_runtime", lambda: (_ for _ in ()).throw(AssertionError("Ticket must not use AI planning")))
    widget.mode_selector.setCurrentIndex(widget.mode_selector.findData("help_ticket"))
    assert widget.mode_selector.currentText() == "Help Ticket"
    monkeypatch.setattr(widget, "_run_worker", lambda work, done, failed: done({"ticket":{"description":"The toolbar stops responding after opening Settings.","category":"hang"}}))
    widget._secretary_busy = True
    widget._secretary_transcript_ready({"ok": True, "transcript": "The toolbar stops responding after opening Settings."})
    assert opened == [(home, "The toolbar stops responding after opening Settings.")]
    assert not widget._secretary_busy
    assert widget.mode_selector.isEnabled()
    widget.cleanup()
    widget.close()


def test_help_ticket_preserves_existing_draft(monkeypatch):
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.home_ui import support_issue_dialog
    from PacsClient.pacs.workstation_ui.home_ui.home_panel import widget as home_module
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    raised = []
    draft = SimpleNamespace(isVisible=lambda: True, raise_=lambda: raised.append(True), activateWindow=lambda: None,
                            public_result={'state':'awaiting_local_input','ticket_submitted':False})
    monkeypatch.setattr(widget, '_watch_help_ticket', lambda dialog:None)
    monkeypatch.setattr(home_module, "get_home_widget", lambda: SimpleNamespace(_support_issue_dialog=draft))
    monkeypatch.setattr(support_issue_dialog, "open_support_issue_form", lambda *args: (_ for _ in ()).throw(AssertionError("Do not overwrite an open draft")))
    widget._open_help_ticket("Another issue description")
    assert raised == [True]
    widget.cleanup()
    widget.close()


def test_existing_received_help_ticket_status_remains_done(monkeypatch):
    from types import SimpleNamespace
    from PacsClient.pacs.workstation_ui.home_ui.home_panel import widget as home_module
    app = QApplication.instance() or QApplication([])
    widget = SecretaryButtonWidget()
    draft = SimpleNamespace(isVisible=lambda:True, raise_=lambda:None, activateWindow=lambda:None,
        public_result={'state':'received','ticket_submitted':True,
                       'issue_id':'4b8b9df2-4874-45c7-adc7-7bff88fbcf97'})
    monkeypatch.setattr(home_module,'get_home_widget',lambda:SimpleNamespace(_support_issue_dialog=draft))
    messages, stages = [], []
    monkeypatch.setattr(widget,'_watch_help_ticket',lambda dialog:None)
    monkeypatch.setattr(widget,'append_output',messages.append)
    monkeypatch.setattr(widget,'_set_thinking_status',stages.append)
    widget._open_help_ticket('Check the previous ticket.',operation='status')
    assert stages[-1] == 'Done'
    assert 'received' in messages[-1] and 'draft' not in messages[-1]
    widget.cleanup()
    widget.close()
