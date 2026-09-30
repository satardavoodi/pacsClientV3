"""GUI-only vector preview for non-pixel structured reports; no file reads."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap


def report_metadata(info):
    info = info if isinstance(info, dict) else {}
    nested = info.get('series')
    fields = dict(info, **nested) if isinstance(nested, dict) else info
    return fields if str(fields.get('modality') or '').strip().upper() == 'SR' else None


def report_pixmap():
    image = QPixmap(160, 120)
    image.fill(QColor('#162438'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#60a5fa'), 2))
    painter.setBrush(QColor('#203954'))
    painter.drawRoundedRect(60, 12, 40, 49, 4, 4)
    painter.setPen(QPen(QColor('#a5d8ff'), 2))
    for y, width in ((25, 22), (33, 22), (41, 16), (49, 20)):
        painter.drawLine(69, y, 69 + width, y)
    font = QFont('Segoe UI', 11)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor('#e6f3ff'))
    painter.drawText(QRect(0, 67, 160, 23), Qt.AlignmentFlag.AlignCenter, 'SR · Report Data')
    font.setPointSize(8)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor('#a7bfd6'))
    painter.drawText(QRect(0, 91, 160, 19), Qt.AlignmentFlag.AlignCenter, 'Drag to read')
    painter.end()
    return image
