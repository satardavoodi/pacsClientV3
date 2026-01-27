import sys
from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QWidget, QFileDialog, QApplication,
    QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QFormLayout, QButtonGroup, QStackedLayout, QGroupBox, QGridLayout
)

class AbstractTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.__main_layout = QHBoxLayout()
        self.setLayout(self.__main_layout)

        self.__lst_buttons = []
        self.__button_group = QButtonGroup()  # manage buttons
        # (we don't need to self.main_layout.addWidget(buttons_group) because it's a helper for manage buttons-layouts )
        self.__button_group.buttonClicked.connect(self.__on_button_click)

        # create left sidebar
        self.__left_sidebar = self.__create_left_sidebar()

        # create toolbar window (up of vtk_widgets)
        toolbar_window = self.__create_toolbar_window()
        self.__vertical_layout = QVBoxLayout()  # it's the right layout on the window
        self.__vertical_layout.addLayout(toolbar_window, stretch=1)
        self.__main_layout.addLayout(self.__vertical_layout)

    def get_sidebar_layout(self):
        return self.__left_sidebar

    def get_center_layout_vertical(self):
        return self.__vertical_layout

    def __on_button_click(self, button):
        id = self.__button_group.id(button)
        self.__stacked_layout.setCurrentIndex(id)

    def __create_left_sidebar(self):
        left_sidebar_widget = QWidget(self)

        # create buttons layout for manage button's layout
        self.__buttons_layout = QFormLayout()
        left_sidebar_layout = QVBoxLayout(left_sidebar_widget)
        left_sidebar_layout.addLayout(self.__buttons_layout, Qt.AlignmentFlag.AlignTop)

        left_sidebar_widget.setContentsMargins(0, 0, 0, 0)
        left_sidebar_widget.setFixedWidth(200)

        self.__main_layout.addWidget(left_sidebar_widget, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # return left_sidebar_widget
        return left_sidebar_layout

    def __create_toolbar_window(self):
        layout = QVBoxLayout()
        # use stacked layout for change tools base on option selected in left-sidebar
        self.__stacked_layout = QStackedLayout()
        layout.addLayout(self.__stacked_layout)
        # layout.addStretch(1)
        return layout

    def add_section(self, name, layout):
        button = QPushButton(name)
        button.setCheckable(True)
        button.setMinimumHeight(30)
        if len(self.__lst_buttons) == 0:  # set check if we have only one section in sidebar
            button.setChecked(True)

        self.__lst_buttons.append(button)
        self.__button_group.addButton(button, id=len(self.__lst_buttons) - 1)  # set behavior clicked btn
        self.__buttons_layout.addRow(button)

        group_box = QGroupBox(name)
        group_box.setLayout(layout)
        self.__stacked_layout.addWidget(group_box)
