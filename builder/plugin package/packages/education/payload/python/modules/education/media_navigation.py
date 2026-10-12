"""Arrow navigation scoped to teaching media; DICOM retains its own keys."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget, QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox


class MediaNavigation(QObject):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, target, event):
        if event.type() not in (QEvent.ShortcutOverride, QEvent.KeyPress):
            return False
        if event.key() not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            return False
        if event.modifiers() != Qt.NoModifier or not isinstance(target, QWidget):
            return False
        viewer = self.viewer
        if getattr(viewer, '_education_closing', False) or not viewer.isVisible():
            return False
        scope = target
        while scope is not None and scope is not viewer:
            scope = scope.parentWidget()
        if scope is not viewer:
            return False
        app = QApplication.instance()
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return False
        if viewer.education_content_stack.currentIndex() != 1:
            return False
        item = viewer.items_list.currentItem()
        payload = item.data(Qt.UserRole) if item else None
        if payload and str(payload.get('content_type', '')).lower() in {'dicom', 'dicom_series', 'dicom_study'}:
            return False
        # Preserve cursor movement and field editing in workstation controls.
        focus = target
        while focus is not None and focus is not viewer:
            if isinstance(focus, (QLineEdit, QComboBox, QAbstractSpinBox)):
                return False
            if isinstance(focus, QTextEdit) and not focus.isReadOnly():
                return False
            focus = focus.parentWidget()
        event.accept()
        if event.type() == QEvent.ShortcutOverride:
            return True
        key = event.key()
        if key == Qt.Key_Left:
            if viewer.current_slide_index > 0:
                viewer._previous_slide()
        elif key == Qt.Key_Right:
            if viewer.current_slide_index + 1 < len(viewer.slides):
                viewer._next_slide()
        else:
            resources = viewer.items_list
            row = resources.currentRow() + (1 if key == Qt.Key_Down else -1)
            if resources.isEnabled() and 0 <= row < resources.count():
                selected = resources.item(row)
                if selected.data(Qt.UserRole):
                    resources.setCurrentRow(row)
                    resources.scrollToItem(selected)
                    viewer._on_item_clicked(selected)
        return True
