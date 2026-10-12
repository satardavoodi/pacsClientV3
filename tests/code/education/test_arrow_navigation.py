"""Real Qt key delivery with a synthetic owner, without clinical initialization."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QStackedWidget, QTextBrowser, QListWidget, QListWidgetItem, QLineEdit
from PySide6.QtTest import QTest
from PySide6.QtGui import QShortcut, QKeySequence


def test_media_arrows_navigate_slides_and_resources_but_dicom_keeps_keys():
    from modules.education.media_navigation import MediaNavigation
    app = QApplication.instance() or QApplication([])
    class Owner(QWidget):
        def _previous_slide(self): self.current_slide_index -= 1
        def _next_slide(self): self.current_slide_index += 1
        def _on_item_clicked(self, item): self.opened.append(item.data(Qt.UserRole))
    owner = Owner()
    owner.current_slide_index = 0
    owner.slides = [{}, {}, {}]
    owner.opened = []
    layout = QVBoxLayout(owner)
    owner.education_content_stack = QStackedWidget()
    dicom = QLineEdit()
    media = QTextBrowser()
    owner.education_content_stack.addWidget(dicom)
    owner.education_content_stack.addWidget(media)
    layout.addWidget(owner.education_content_stack)
    owner.items_list = QListWidget()
    for i in range(3):
        item = QListWidgetItem(str(i))
        item.setData(Qt.UserRole, {'content_type': 'multimedia', 'id': i})
        owner.items_list.addItem(item)
    layout.addWidget(owner.items_list)
    owner.items_list.setCurrentRow(0)
    navigation = MediaNavigation(owner)
    owner.resize(640, 480)
    owner.show()
    owner.education_content_stack.setCurrentIndex(1)
    media.setFocus()
    app.processEvents()
    QTest.keyClick(media, Qt.Key_Right)
    assert owner.current_slide_index == 1
    QTest.keyClick(media, Qt.Key_Left)
    assert owner.current_slide_index == 0
    QTest.keyClick(media, Qt.Key_Left)
    assert owner.current_slide_index == 0
    QTest.keyClick(media, Qt.Key_Down)
    assert owner.items_list.currentRow() == 1 and owner.opened[-1]['id'] == 1
    QTest.keyClick(owner.items_list, Qt.Key_Up)
    assert owner.items_list.currentRow() == 0 and owner.opened[-1]['id'] == 0
    QTest.keyClick(media, Qt.Key_Right, Qt.ControlModifier)
    assert owner.current_slide_index == 0
    owner.items_list.setCurrentRow(2)
    count = len(owner.opened)
    QTest.keyClick(media, Qt.Key_Down)
    assert owner.items_list.currentRow() == 2 and len(owner.opened) == count
    # A DICOM resource selected before deferred dispatch must retain its keys too.
    owner.items_list.currentItem().setData(Qt.UserRole, {'content_type': 'dicom_series'})
    QTest.keyClick(media, Qt.Key_Right)
    assert owner.current_slide_index == 0
    owner.items_list.setCurrentRow(0)
    editor = QLineEdit(owner)
    layout.addWidget(editor)
    editor.setText('ABC')
    editor.setCursorPosition(1)
    QTest.keyClick(editor, Qt.Key_Right)
    assert editor.cursorPosition() == 2 and owner.current_slide_index == 0
    audience = QWidget(owner, Qt.Window)
    other_shortcut_calls = []
    shortcut = QShortcut(QKeySequence('Right'), audience)
    shortcut.activated.connect(lambda: other_shortcut_calls.append(True))
    audience.show()
    audience.setFocus()
    app.processEvents()
    QTest.keyClick(audience, Qt.Key_Right)
    assert owner.current_slide_index == 1 and not other_shortcut_calls
    QTest.keyClick(audience, Qt.Key_Down)
    assert owner.items_list.currentRow() == 1
    audience.close()
    owner.current_slide_index = 0
    owner.education_content_stack.setCurrentIndex(0)
    dicom.setText('ABC')
    dicom.setCursorPosition(1)
    dicom.setFocus()
    QTest.keyClick(dicom, Qt.Key_Right)
    assert dicom.cursorPosition() == 2 and owner.current_slide_index == 0
    owner.close()
    navigation.deleteLater()
    owner.deleteLater()
    app.processEvents()
