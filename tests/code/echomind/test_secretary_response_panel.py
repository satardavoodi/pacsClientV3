from PySide6.QtWidgets import QApplication

def test_response_panel_preserves_text_without_speech():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    panel = SecretaryResponsePanel(speech_factory=lambda parent: None)
    panel.set_response("Completed synthetic action.")
    assert panel.text.toPlainText() == "Completed synthetic action."
    assert not panel.play.isEnabled()
    assert not panel.auto_voice.isChecked()
    panel.close()

def test_speech_replaces_previous_response_and_stops_on_close():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    class Speech:
        def __init__(self): self.calls=[]
        def say(self,text): self.calls.append(text)
        def stop(self): self.calls.append("STOP")
    speech=Speech()
    panel=SecretaryResponsePanel(speech_factory=lambda parent:speech)
    panel.auto_voice.setChecked(True)
    panel.set_response("First synthetic response.")
    panel.set_response("Second synthetic response.")
    assert speech.calls[-2:]==["STOP","Second synthetic response."]
    panel.close()
    assert speech.calls[-1]=="STOP"


def test_automatic_reply_occupies_middle_header_third_and_tracks_resize():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    panel = SecretaryResponsePanel(host, speech_factory=lambda _: None)
    panel.set_response('The patient list is ready on screen.')
    panel.open_response()
    app.processEvents()
    assert not panel.isWindow()
    assert panel.x() == 400 and panel.width() == 400
    assert panel.geometry().bottom() < 80
    assert panel.command_input.isHidden()
    host.resize(900, 700)
    app.processEvents()
    assert panel.x() == 300 and panel.width() == 300
    panel.open_response(expanded=True)
    app.processEvents()
    assert not panel.isWindow() and panel.command_input.isVisible()
    assert panel.x() == 300 and panel.y() == 8 and panel.width() == 300
    assert panel.height() > 68
    panel.expand_button.click()
    app.processEvents()
    assert panel.height() == 70 and panel.command_input.isHidden()
    assert panel.text.toPlainText() == 'The patient list is ready on screen.'
    panel.close()
    host.close()


def test_secretary_icon_drag_is_horizontal_bounded_and_retained():
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QWidget
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(900, 700)
    host.show()
    panel = SecretaryResponsePanel(host, speech_factory=lambda _: None)
    panel.open_response()
    app.processEvents()
    assert not panel.secretary_icon.pixmap().isNull()
    icon = panel.secretary_icon
    def mouse(kind, x, button, buttons):
        event = QMouseEvent(kind, QPointF(5, 5), QPointF(x, 40), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(icon, event)
    mouse(QEvent.MouseButtonPress, 400, Qt.LeftButton, Qt.LeftButton)
    mouse(QEvent.MouseMove, 550, Qt.NoButton, Qt.LeftButton)
    assert panel.x() == 450 and panel.y() == 8
    mouse(QEvent.MouseMove, 5000, Qt.NoButton, Qt.LeftButton)
    assert panel.x() + panel.width() == host.width()
    mouse(QEvent.MouseButtonRelease, 5000, Qt.LeftButton, Qt.NoButton)
    panel.open_response()
    app.processEvents()
    assert panel.x() + panel.width() == host.width()
    host.resize(1200, 800)
    app.processEvents()
    assert panel.x() + panel.width() == host.width()
    panel.close()
    host.close()


def test_expanded_panel_paints_opaque_surface_between_controls():
    from PySide6.QtWidgets import QWidget
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(1200, 800)
    host.setStyleSheet('background-color: #ff00ff;')
    host.show()
    panel = SecretaryResponsePanel(host, speech_factory=lambda _: None)
    panel.open_response(expanded=True)
    app.processEvents()
    image = panel.grab().toImage()
    # Sample the uninterrupted surface inside the border, beside the controls.
    color = image.pixelColor(3, panel.height() // 2)
    assert color.name() == '#172334'
    assert color.alpha() == 255
    panel.close()
    host.close()


def test_collapsed_panel_matches_live_logo_geometry():
    from PySide6.QtWidgets import QWidget, QPushButton
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(1200, 800)
    logo = QPushButton(host)
    logo.setObjectName("LogoButton")
    logo.setGeometry(10, 3, 165, 70)
    host.show()
    panel = SecretaryResponsePanel(host, speech_factory=lambda _: None)
    panel.open_response()
    app.processEvents()
    assert panel.y() == logo.y() and panel.height() == logo.height()
    assert not panel.expand_button.icon().isNull()
    panel.close()
    host.close()


def test_response_text_scrollbar_has_visible_shared_arrows():
    from PacsClient.pacs.workstation_ui.home_ui.secretary_response_panel import SecretaryResponsePanel
    app = QApplication.instance() or QApplication([])
    panel = SecretaryResponsePanel(speech_factory=lambda _: None)
    panel.set_response("\n".join(f"Synthetic line {i}" for i in range(100)))
    panel.open_response(expanded=True)
    app.processEvents()
    bar = panel.text.verticalScrollBar()
    assert bar.maximum() > 0
    assert "keyboard_arrow_up.png" in bar.styleSheet()
    assert "keyboard_arrow_down.png" in bar.styleSheet()
    bar.triggerAction(bar.SliderAction.SliderSingleStepAdd)
    assert bar.value() > 0
    panel.close()
