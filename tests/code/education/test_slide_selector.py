from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from modules.education.slide_selector import SlideSelector


def test_numbered_cards_reflow_without_losing_order_or_selection():
    app = QApplication.instance() or QApplication([])
    selector = SlideSelector()
    titles = [f'Synthetic slide {i}: Assessment of morphology and lesion stability' for i in range(1, 8)]
    for i, title in enumerate(titles, 1):
        selector.add_slide(i, title)
    selector.resize(850, 240)
    selector.show()
    for _ in range(3): app.processEvents()
    first, second, third = [selector.visualItemRect(selector.item(i)) for i in range(3)]
    assert first.top() == second.top() and third.top() > first.top()
    assert not selector.item(0).icon().isNull()
    QTest.mouseClick(selector.viewport(), Qt.LeftButton, pos=second.center())
    assert selector.currentRow() == 1
    selector.resize(500, 240)
    for _ in range(3): app.processEvents()
    assert selector.visualItemRect(selector.item(1)).top() > selector.visualItemRect(selector.item(0)).top()
    assert selector.currentRow() == 1
    assert [selector.item(i).text() for i in range(7)] == titles
    assert selector.horizontalScrollBar().maximum() == 0
    assert selector.verticalScrollBar().maximum() > 0
    assert titles[6] in selector.item(6).toolTip()
    selector.close()
