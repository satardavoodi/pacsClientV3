"""OS printer handler using Qt printing (placeholder)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog


class OSPrinterHandler:
    def list_printers(self) -> list[str]:
        try:
            return [printer.printerName() for printer in QPrinterInfo.availablePrinters()]
        except Exception:
            return []

    def print_film(self, film_pixmap: Any, printer_name: str | None = None) -> bool:
        if film_pixmap is None:
            return False

        printer = QPrinter(QPrinter.HighResolution)
        if printer_name:
            printer.setPrinterName(printer_name)

        dialog = QPrintDialog(printer)
        if dialog.exec() != QPrintDialog.Accepted:
            return False

        painter = QPainter(printer)
        if not painter.isActive():
            return False

        rect = painter.viewport()
        pixmap = film_pixmap
        scaled = pixmap.scaled(rect.size(), aspectMode=Qt.KeepAspectRatio)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        return True
