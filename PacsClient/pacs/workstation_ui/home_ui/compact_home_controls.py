"""Compact presentation of existing Home view actions, preserving callbacks."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QWidget


def mount_view_controls(table, adaptive):
    decrease, increase = table.font_decrease_btn, table.font_increase_btn
    parent = increase.parentWidget()
    layout = parent.layout()
    index = layout.indexOf(decrease)
    group = QWidget(parent)
    group.setObjectName('homeViewControls')
    row = QHBoxLayout(group)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(2)
    adaptive.setText('')
    adaptive.setAccessibleName('Adaptive to Screen Size')
    for button in (decrease, increase, adaptive):
        layout.removeWidget(button)
        button.setFixedSize(30, 32)
        button.setIconSize(QSize(14, 14))
        row.addWidget(button)
    # Keep surplus header width outside the cluster, independent of result text.
    group.setFixedSize(94, 32)
    layout.insertWidget(index, group)
    adaptive.show()
    return group
