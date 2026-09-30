from PySide6.QtWidgets import QApplication, QListWidgetItem, QStyleOptionViewItem
from PySide6.QtCore import Qt
from modules.education.authoring_list import AuthoringListWidget


def test_long_titles_wrap_and_rows_grow_when_column_narrows():
    app = QApplication.instance() or QApplication([])
    view = AuthoringListWidget()
    title = "Knee - Supplementary Material - " + "Detailed teaching case " * 15
    view.addItem(QListWidgetItem(title))
    view.resize(600, 500)
    view.show()
    app.processEvents()
    index = view.model().index(0, 0)
    option = QStyleOptionViewItem()
    wide = view.itemDelegate().sizeHint(option, index).height()
    view.resize(290, 500)
    app.processEvents()
    narrow = view.itemDelegate().sizeHint(option, index).height()
    assert narrow > wide >= 80
    assert view.item(0).text() == title
    assert view.textElideMode() == Qt.ElideNone
    view.close()

def test_item_grid_uses_two_columns_and_reflows_without_losing_selection():
    app = QApplication.instance() or QApplication([])
    view = AuthoringListWidget(two_columns=True)
    for number in range(5):
        view.addItem(QListWidgetItem(f"{number + 1}. Synthetic teaching item with a complete title"))
    view.resize(1000, 500)
    view.show()
    for _ in range(4):
        app.processEvents()
    rects = [view.visualItemRect(view.item(i)) for i in range(5)]
    assert rects[0].top() == rects[1].top()
    assert rects[1].left() > rects[0].right()
    assert rects[2].top() > rects[0].bottom()
    assert all(view.viewport().rect().contains(rect) for rect in rects)
    view.setCurrentRow(3)
    view.resize(600, 600)
    for _ in range(4):
        app.processEvents()
    assert view.visualItemRect(view.item(1)).top() > view.visualItemRect(view.item(0)).bottom()
    assert view.currentRow() == 3
    view.close()


def test_item_number_is_larger_and_bold_without_changing_title():
    from PySide6.QtGui import QFont
    app = QApplication.instance() or QApplication([])
    view = AuthoringListWidget(two_columns=True)
    font = QFont("Segoe UI", 10)
    text = "12. IMAGE | Teaching example"
    layout, _ = view.itemDelegate()._layout(text, font, 300)
    formats = layout.formats()
    assert len(formats) == 1
    assert formats[0].start == 0 and formats[0].length == 3
    assert formats[0].format.fontWeight() >= QFont.Bold
    assert formats[0].format.fontPointSize() >= 15
    assert layout.text() == text
    view.close()
