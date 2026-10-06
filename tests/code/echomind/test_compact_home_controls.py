"""Existing toolbar actions keep their identity, order and signal connections."""
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QPushButton
from PacsClient.pacs.workstation_ui.home_ui.compact_home_controls import mount_view_controls


def test_view_controls_move_without_recreating_actions():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QHBoxLayout(host)
    before, decrease, increase, after = [QPushButton(x) for x in ('Count', 'A-', 'A+', 'Refresh')]
    for button in (before, decrease, increase, after):
        layout.addWidget(button)
    adaptive = QPushButton('Adaptive to Screen Size')
    calls = []
    adaptive.clicked.connect(lambda: calls.append('adaptive'))
    group = mount_view_controls(SimpleNamespace(font_decrease_btn=decrease, font_increase_btn=increase), adaptive)
    assert layout.itemAt(1).widget() is group
    assert layout.itemAt(2).widget() is after
    assert [group.layout().itemAt(i).widget() for i in range(3)] == [decrease, increase, adaptive]
    assert group.layout().spacing() == 2
    assert adaptive.accessibleName() == 'Adaptive to Screen Size'
    adaptive.click()
    assert calls == ['adaptive']
    assert all(button.width() == 30 for button in (decrease, increase, adaptive))
    # A short result caption must not donate width to the action cluster.
    host.resize(1000, 80)
    host.show()
    app.processEvents()
    assert group.width() == 94
    host.resize(600, 80)
    app.processEvents()
    assert group.width() == 94
    host.close()
