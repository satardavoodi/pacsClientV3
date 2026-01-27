from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QPushButton
)


class MatrixButton(QPushButton):

    def __init__(self, row, col, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row = row
        self.col = col
        # self.setFixedSize(20, 20)
        self.setStyleSheet("QPushButton { border: 1px solid #90caf9; background-color: transparent; }")

    def enterEvent(self, event):
        self.highlight_buttons(self.row, self.col)
        super().enterEvent(event)

    def set_method_highlight_buttons(self, method_highlight_buttons):
        self.highlight_buttons = method_highlight_buttons


class MatrixSelector(QWidget):

    def __init__(self, max_rows=4, max_cols=4, parent=None):
        super().__init__()
        self.max_rows = max_rows
        self.max_cols = max_cols
        self.menu_parent = parent
        self.layout = QGridLayout(self)
        self.layout.setSpacing(5)
        self.layout.setContentsMargins(5, 5, 5, 5)
        # self.setLayoutDirection(Qt.LeftToRight)

        self.buttons = []
        for i in range(max_rows):
            row_buttons = []
            for j in range(max_cols):
                btn = MatrixButton(i, j)
                btn.set_method_highlight_buttons(self.highlight_up_to)
                # btn.clicked.connect(lambda _, r=i, c=j: self.apply_multi_viewer((r + 1, c + 1)))
                btn.clicked.connect(lambda _, r=i, c=j: self.close_menu_and_apply_multi_viewer((r + 1, c + 1)))
                self.layout.addWidget(btn, i, j)
                row_buttons.append(btn)
            self.buttons.append(row_buttons)

    def highlight_up_to(self, row, col):
        for i in range(self.max_rows):
            for j in range(self.max_cols):
                btn = self.buttons[i][j]
                if i <= row and j <= col:
                    btn.setStyleSheet("""
                        QPushButton {
                            border: 1px solid #90caf9;
                            background-color: #90caf9;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            border: 1px solid #90caf9;
                            background-color: transparent;
                        }
                    """)

    def set_method_change_viewers(self, method_apply_multi_viewer):
        self.apply_multi_viewer = method_apply_multi_viewer

    def close_menu_and_apply_multi_viewer(self, numbers):
        self.apply_multi_viewer(numbers, modify_by_user=True)
        self.menu_parent.close()